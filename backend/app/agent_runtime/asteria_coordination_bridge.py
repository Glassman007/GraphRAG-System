"""Opt-in adapter between Asteria Supervisor DAGs and existing Phase-6 handoff services.

This is agent telemetry, not business actions. The Supervisor owns scheduling and
terminal task status; Phase-6 execution completion is NOT fabricated by this adapter.
"""
from __future__ import annotations

import hashlib
import json

from backend.app.agent_runtime.supervisor import SpecialistFinding
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.services.agent_registry_service import AgentRegistryService
from backend.app.services.coordination_service import CoordinationService
from backend.app.services.handoff_service import HandoffService
from backend.app.services.phase4_graph import GraphSnapshot, has_label


ROLE = {
    'dependency_analysis': ('AGENT-P6-DEPENDENCY', 'INVESTIGATE'),
    'evidence_retrieval': ('AGENT-P6-INVESTIGATOR', 'ACQUIRE_EVIDENCE'),
    'investigation': ('AGENT-P6-INVESTIGATOR', 'INVESTIGATE'),
    'verification': ('AGENT-P6-VERIFIER', 'VERIFY_CLAIM'),
    'remediation_proposal': ('AGENT-P6-REMEDIATION', 'PREPARE_ACTION'),
}


def _canonical(result):
    return SpecialistFinding.model_validate(result).model_dump()


def _digest(result):
    return hashlib.sha256(json.dumps(_canonical(result), sort_keys=True).encode()).hexdigest()


class AsteriaCoordinationBridge:
    """Thin adapter; all formal acceptance/blackboard operations use existing services."""

    def __init__(self, client, run_id: str, source: str, tasks: dict):
        if client.settings.tenant_id != 'asteria' or client.settings.falkordb_graph != 'asteria_company_brain_v1':
            raise PermissionError('Asteria bridge cannot access another graph or tenant')
        self.client = client
        self.run_id = run_id
        self.source = source
        self.tasks = tasks
        self.coordination = CoordinationService(client)
        self.handoffs = HandoffService(client)
        self.task_ids = {name: f'TASK-VERINEX-{run_id}-{name}' for name in tasks}
        self.plan_id = f'PLAN-VERINEX-{run_id}'

    def prepare(self):
        AgentRegistryService(self.client).ensure_default_agents()
        snapshot = GraphSnapshot.load(self.client)
        if not has_label(snapshot.node(self.source), 'Incident'):
            raise ValueError('BRIDGE_SOURCE_NOT_INCIDENT')
        upsert_node(self.client, 'Plan', self.plan_id, {
            'name': 'VERINEX read-only investigation', 'source_entity_id': self.source,
            'run_id': self.run_id, 'status': 'IN_PROGRESS',
        })
        for name, state in self.tasks.items():
            _, task_type = ROLE[state.capability]
            ident = self.task_ids[name]
            old = snapshot.node(ident)
            if old and (not has_label(old, 'Task') or old.get('run_id') != self.run_id):
                raise ValueError('BRIDGE_TASK_ID_COLLISION')
            if not old:
                upsert_node(self.client, 'Task', ident, {
                    'title': state.objective[:140], 'task_type': task_type,
                    'status': 'OPEN', 'run_id': self.run_id,
                    'supervisor_task_id': name, 'source_entity_id': self.source,
                })
            upsert_relationship(self.client, self.plan_id, 'PLAN_HAS_TASK', ident)

    def begin(self, state):
        graph_task = self.task_ids[state.id]
        actor = ROLE[state.capability][0]
        owner = (self.coordination.get_task_owner(graph_task) or {}).get('owner') or {}
        if owner.get('id') != actor:
            self.coordination.claim_task(graph_task, actor)
        self.coordination.start_execution(graph_task, actor)

    def _existing_accepted(self, from_name: str, to_name: str):
        board = self.coordination.get_task_blackboard(self.task_ids[to_name])
        if not board:
            raise ValueError('BRIDGE_BLACKBOARD_MISSING')
        matches = [item for item in board['accepted_handoff_context']
                   if item['handoff'].get('source_task_id') == self.task_ids[from_name]
                   and item['handoff'].get('destination_task_id') == self.task_ids[to_name]]
        if len(matches) > 1:
            raise ValueError('BRIDGE_DUPLICATE_ACCEPTED_HANDOFF')
        return matches[0] if matches else None

    def publish(self, state, dependents: list):
        """Persist predecessor finding and accepted, verified receiver contracts."""
        result = _canonical(state.result)
        if result['confidence'] == 'insufficient' or not result['citations']:
            raise ValueError('BRIDGE_INSUFFICIENT_FINDING')
        snapshot = GraphSnapshot.load(self.client)
        if any(snapshot.node(cid) is None for cid in result['citations']):
            raise ValueError('BRIDGE_UNKNOWN_CITATION')
        agent_id = ROLE[state.capability][0]
        task_id = self.task_ids[state.id]
        evidence_ids = [cid for cid in result['citations'] if has_label(snapshot.node(cid), 'Evidence')]
        existing = [item for item in self.coordination.get_recent_findings(task_id)
                    if item.get('created_by') == agent_id and item.get('supervisor_digest') == _digest(result)]
        if existing:
            finding_id = existing[0]['id']
        else:
            finding = self.coordination.add_finding(
                task_id, agent_id, statement=result['summary'],
                confidence=0.6 if result['confidence'] == 'uncertain' else 0.85,
                kind='VERINEX_READ_ONLY', evidence_ids=evidence_ids,
            )['finding']
            finding_id = finding['id']
            upsert_node(self.client, 'Finding', finding_id, {
                'supervisor_digest': _digest(result),
                'supervisor_result_json': json.dumps(result, sort_keys=True),
                'supervisor_run_id': self.run_id,
            })
        handoff_ids = []
        for to_name in dependents:
            receiver = ROLE[self.tasks[to_name].capability][0]
            if receiver == agent_id:
                raise ValueError('BRIDGE_SAME_AGENT_HANDOFF')
            existing_handoff = self._existing_accepted(state.id, to_name)
            if existing_handoff:
                hid = existing_handoff['handoff']['id']
                artifacts = existing_handoff['artifacts']
                if not any(a.get('id') == finding_id for a in artifacts):
                    raise ValueError('BRIDGE_ACCEPTED_HANDOFF_ARTIFACT_CHANGED')
            else:
                # Investigator -> Verifier has a mandatory Evidence plus Finding contract.
                artifact_ids = [finding_id, *evidence_ids[:8]]
                if agent_id == 'AGENT-P6-INVESTIGATOR' and receiver == 'AGENT-P6-VERIFIER' and not evidence_ids:
                    raise ValueError('BRIDGE_REQUIRED_EVIDENCE_MISSING')
                detail = self.handoffs.create_handoff(
                    task_id, agent_id, receiver, artifact_ids=artifact_ids,
                    destination_task_id=self.task_ids[to_name], confidence_threshold=0.6,
                    contradictory_evidence_disclosed=True,
                )
                hid = detail['handoff']['id']
                validation = self.handoffs.validate_handoff(hid)
                if not validation['valid']:
                    raise ValueError('BRIDGE_HANDOFF_INVALID: ' + ','.join(validation['errors']))
                self.handoffs.accept_handoff(hid, receiver)
            handoff_ids.append(hid)
        return handoff_ids

    def consume(self, from_name: str, to_name: str):
        """Read typed predecessor result from the persisted accepted blackboard artifact."""
        record = self._existing_accepted(from_name, to_name)
        if record is None:
            raise ValueError('BRIDGE_HANDOFF_NOT_ACCEPTED')
        handoff = record['handoff']
        if handoff.get('to_agent_id') != ROLE[self.tasks[to_name].capability][0]:
            raise ValueError('BRIDGE_RECEIVER_MISMATCH')
        findings = [a for a in record['artifacts'] if has_label(a, 'Finding')
                    and a.get('task_id') == self.task_ids[from_name]
                    and a.get('created_by') == ROLE[self.tasks[from_name].capability][0]]
        if len(findings) != 1:
            raise ValueError('BRIDGE_FINDING_CARDINALITY')
        original = findings[0]
        data = original.get('supervisor_result_json')
        if not data:
            raise ValueError('BRIDGE_FINDING_MISSING_TYPED_RESULT')
        result = _canonical(json.loads(data))
        if _digest(result) != original.get('supervisor_digest'):
            raise ValueError('BRIDGE_FINDING_DIGEST_MISMATCH')
        snapshot = GraphSnapshot.load(self.client)
        if any(snapshot.node(cid) is None for cid in result['citations']):
            raise ValueError('BRIDGE_STALE_CITATION')
        linked = {edge.target for edge in snapshot.edges_from(original['id'], {'DERIVED_FROM'})}
        for citation in result['citations']:
            if has_label(snapshot.node(citation), 'Evidence') and citation not in linked:
                raise ValueError('BRIDGE_EVIDENCE_NOT_LINKED')
        return {'task_id': from_name, 'agent_id': self.tasks[from_name].agent_id,
                'result': result, 'handoff_id': handoff['id'], 'artifact_ids': [a['id'] for a in record['artifacts']]}
