"""Component 4: deterministic organizational change propagation.

Only committed, authoritative ingestion deltas can invalidate trusted agent memory.
Uncertain input is a review event, not an automatic rewrite of organizational truth.
No external model calls or business actions occur in this processor.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from backend.app.agent_runtime.memory import AgentMemory, utcnow
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.knowledge_invalidation_service import KnowledgeInvalidationService

# Ignore write bookkeeping, source record ingestion stamps, and arbitrary unvalidated prose.
FACT_FIELDS = frozenset({'name', 'status', 'severity', 'criticality', 'owner_id',
                         'source_type', 'policy_version', 'approval_status', 'resolution_status'})
RELATION_TYPES = frozenset({'DEPENDS_ON', 'OWNS', 'OWNED_BY', 'SUPPORTS', 'CONTRADICTS',
                            'GOVERNED_BY', 'AFFECTS', 'BLOCKS', 'PROPOSED_ACTION',
                            'ABOUT', 'EVIDENCED_BY', 'DERIVED_FROM'})


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, separators=(',', ':')).encode()).hexdigest()


def _visible_edges(snapshot: GraphSnapshot, entity_id: str) -> list[tuple[str, str, str]]:
    return sorted({(e.source, e.type, e.target) for e in snapshot.edges
                   if e.type in RELATION_TYPES and (e.source == entity_id or e.target == entity_id)
                   and snapshot._edge_active(e, None)})


def graph_delta(before: GraphSnapshot, after: GraphSnapshot, candidates: list[str]) -> list[dict]:
    """Actual before/after graph comparison; unchanged reingestion cannot fake a change."""
    changes = []
    for entity_id in sorted(set(candidates))[:1000]:
        old = before.node(entity_id) or {}
        new = after.node(entity_id) or {}
        fields = {field: {'before': old.get(field), 'after': new.get(field)}
                  for field in FACT_FIELDS if old.get(field) != new.get(field)}
        prior, current = set(_visible_edges(before, entity_id)), set(_visible_edges(after, entity_id))
        added, removed = sorted(current - prior), sorted(prior - current)
        if not fields and not added and not removed:
            continue
        changes.append({'entity_id': entity_id, 'fields': fields,
                        'edges_added': [list(x) for x in added],
                        'edges_removed': [list(x) for x in removed]})
    return changes


class ReactiveLearning:
    """Run durable event work with explicit trust boundaries and impact lineage."""

    def __init__(self, *, store: Any, memory: AgentMemory, snapshot_factory: Callable[[], GraphSnapshot], tenant: str):
        self.store, self.memory, self.snapshot_factory, self.tenant = store, memory, snapshot_factory, tenant

    def publish(self, *, source_record_id: str, source_checksum: str, changes: list[dict],
                authority: str, ingestion_run_id: str, source_id: str) -> dict | None:
        if not changes:
            return None
        # Authentication of source authority is performed by the ingestion source registry,
        # never by a caller-supplied API field.
        confidence = 'CONFIRMED' if authority == 'AUTHORITATIVE' else 'PROBABLE'
        material = {'tenant': self.tenant, 'source_record': source_record_id,
                    'checksum': source_checksum, 'changes': changes}
        event_id = 'RCHANGE-' + _digest(material)[:32].upper()
        ids = sorted(set([item['entity_id'] for item in changes] +
                         [end for item in changes for edge in
                          (item['edges_added'] + item['edges_removed']) for end in (edge[0], edge[2])]))
        event = {'id': event_id, 'tenant_id': self.tenant, 'status': 'PENDING',
                 'confidence': confidence, 'kind': 'GRAPH_FACT_CHANGED', 'changed_ids': ids,
                 'changes': changes, 'source_record_id': source_record_id,
                 'source_id': source_id, 'ingestion_run_id': ingestion_run_id,
                 'source_checksum': source_checksum, 'occurred_at': utcnow(),
                 'attempts': 0, 'max_attempts': 3, 'memory_impacts': [],
                 'workflow_impacts': [], 'notifications': [], 'outcomes': []}
        return self.store.enqueue(event)  # MERGE once; never reset a delivered event

    def process(self, *, limit: int = 20) -> list[dict]:
        completed = []
        for _ in range(max(0, min(limit, 100))):
            event = self.store.claim()  # durable, lease-based compare-and-set
            if not event:
                break
            try:
                result = self._apply(event)
                self.store.finish(event['id'], token=event['lease_token'], result=result)
                completed.append(result)
            except Exception as exc:
                self.store.fail(event['id'], token=event['lease_token'],
                                error=f'{type(exc).__name__}: {str(exc)[:180]}')
                # Do not swallow the error as success. Persisted retry queue survives restarts.
        return completed

    def _apply(self, event: dict) -> dict:
        if event['tenant_id'] != self.tenant:
            raise PermissionError('Cross-tenant event denied')
        if event['confidence'] != 'CONFIRMED':
            return {'id': event['id'], 'status': 'NEEDS_REVIEW', 'confidence': event['confidence'],
                    'memory_impacts': [], 'workflow_impacts': [],
                    'notifications': [{'type': 'UNCONFIRMED_SOURCE_CHANGE', 'event_id': event['id'],
                                       'message': 'Source evidence is probable; no trusted claim was withdrawn'}]}

        snapshot = self.snapshot_factory()
        ids = set(event['changed_ids'])
        legacy_impacts = []
        # Traverse declared Company Brain evidence -> claim -> decision -> task -> plan
        # dependencies without assuming unrelated neighboring nodes are affected.
        seen_legacy = set()
        for subject_id in sorted(ids):
            for item in KnowledgeInvalidationService.impact_from_snapshot(snapshot, subject_id)['actions']:
                key = (item['entity_id'], item['action'])
                if key not in seen_legacy:
                    seen_legacy.add(key)
                    legacy_impacts.append({'trigger_id': subject_id, **item})
            for edge in snapshot.edges_from(subject_id, {'ABOUT', 'INVESTIGATES'}):
                node = snapshot.node(edge.target)
                if has_label(node, 'Investigation'):
                    key = (edge.target, 'REVISIT_INVESTIGATION')
                    if key not in seen_legacy:
                        seen_legacy.add(key)
                        legacy_impacts.append({'trigger_id': subject_id, 'entity_id': edge.target,
                                               'action': 'REVISIT_INVESTIGATION'})
            for edge in snapshot.edges_to(subject_id, {'ABOUT', 'INVESTIGATES'}):
                node = snapshot.node(edge.source)
                if has_label(node, 'Investigation'):
                    key = (edge.source, 'REVISIT_INVESTIGATION')
                    if key not in seen_legacy:
                        seen_legacy.add(key)
                        legacy_impacts.append({'trigger_id': subject_id, 'entity_id': edge.source,
                                               'action': 'REVISIT_INVESTIGATION'})
        # A *confirmed explicit Evidence invalidation* uses existing Phase 7
        # semantics to cascade recorded stale flags to claims/decisions/tasks/plans.
        # Other fact changes are tracked for review, not blindly invalidated.
        for delta in event.get('changes') or []:
            node = snapshot.node(delta['entity_id'])
            state = (delta.get('fields') or {}).get('status') or {}
            if (has_label(node, 'Evidence') and state.get('after') == 'INVALIDATED' and
                    state.get('before') != 'INVALIDATED' and getattr(self.store, 'client', None)):
                KnowledgeInvalidationService(self.store.client).invalidate_evidence(
                    delta['entity_id'], reason='Source-confirmed invalidation '+event['id'])
        impacted_memories = []
        # Only shared verified records. Draft/private branches remain private.
        for record in self.store.affected_memories(sorted(ids)):
            if (record.get('tenant_id') != self.tenant or record.get('status') != 'VERIFIED' or
                    record.get('scope') != 'SHARED' or record.get('last_change_event_id') == event['id']):
                continue
            # The verified assertion must still match canonical source truth.
            source_ok = self.memory._source_ok(record.get('citations') or [])
            valid = bool(source_ok and self.memory._fact_matches(record))
            revised = dict(record)
            revised['revision'] = int(record.get('revision') or 0) + 1
            revised['updated_at'] = utcnow()
            revised['last_change_event_id'] = event['id']
            if valid:
                revised['verification_confidence'] = 'CONFIRMED'
                revised['last_rechecked_at'] = utcnow()
                revised['last_rechecked_by'] = 'reactive_graph_verifier'
                decision = 'REVERIFIED'
            else:
                revised.update(status='RECHECK_REQUIRED', scope='PRIVATE',
                               verification_confidence='CONTRADICTED' if source_ok else 'MISSING_EVIDENCE',
                               review_reason='Confirmed source change invalidated or removed supporting graph evidence',
                               reviewed_by='reactive_graph_verifier')
                decision = 'STALE'
            # Immutable pre-change version and guarded revision update. Safe on replay.
            self.store.revise_memory(record, revised, event_id=event['id'])
            impacted_memories.append({'memory_id': record['id'], 'decision': decision,
                                      'subject_id': record['subject_id'], 'previous_revision': record.get('revision')})

        impacted_runs = []
        for cp in self.store.affected_checkpoints(sorted(ids)):
            if (cp.get('tenant') != self.tenant or not cp.get('owner') or
                    event['id'] in (cp.get('reactive_change_event_ids') or [])):
                continue
            affected = set()
            for task in cp.get('tasks') or []:
                if set((task.get('result') or {}).get('citations') or []) & ids:
                    affected.add(task['id'])
            if cp.get('source') in ids and not affected:
                # The starting object changed: recheck all tasks without citations yet.
                affected.update(t['id'] for t in cp.get('tasks') or [])
            # Anything depending on invalidated tasks must be reconsidered.
            while True:
                added = {t['id'] for t in cp.get('tasks') or []
                         if set(t.get('depends_on') or []) & affected}
                if added <= affected:
                    break
                affected |= added
            if not affected:
                continue
            revision = int(cp.get('revision') or 0) + 1
            updated = dict(cp)
            updated['status'] = 'REPLAN_REQUIRED'
            updated['reactive_affected_tasks'] = sorted(affected)
            updated['reactive_change_event_ids'] = sorted(set(cp.get('reactive_change_event_ids') or []) | {event['id']})
            updated['revision'] = revision
            updated['updated_at'] = utcnow()
            # No implicit network call: fresh model consent + currently authorized principal
            # is required to restart those tasks. An internal work item is automatically queued.
            self.store.revise_checkpoint(cp, updated, event_id=event['id'])
            impacted_runs.append({'run_id': cp['id'], 'affected_task_ids': sorted(affected),
                                  'status': 'REPLAN_REQUIRED', 'requires_model_consent': True})
        notifications = []
        if legacy_impacts:
            notifications.append({'type': 'DEPENDENT_ORGANIZATIONAL_RECORDS', 'event_id': event['id'],
                                  'message': f'{len(legacy_impacts)} claim/decision/task/plan/investigation review targets identified'})
        if impacted_runs:
            notifications.append({'type': 'WORKFLOW_PAUSED', 'event_id': event['id'],
                                  'message': f'{len(impacted_runs)} run(s) require targeted replan / fresh model authorization'})
        if any(m['decision'] == 'STALE' for m in impacted_memories):
            notifications.append({'type': 'KNOWLEDGE_STALE', 'event_id': event['id'],
                                  'message': 'Previously verified claims became unsupported by current evidence'})
        return {'id': event['id'], 'status': 'COMPLETED', 'confidence': 'CONFIRMED',
                'memory_impacts': impacted_memories, 'workflow_impacts': impacted_runs,
                'legacy_impacts': legacy_impacts[:500], 'notifications': notifications}

    def learn_action_outcome(self, *, action_id: str) -> dict:
        """Record only a terminal, canonical action state, with actual attempt provenance."""
        snapshot = self.snapshot_factory()
        action = snapshot.node(action_id)
        if not action or 'Action' not in (action.get('_labels') or []):
            raise ValueError('Canonical Action not found')
        state = str(action.get('status') or '')
        if state not in {'SUCCEEDED', 'FAILED', 'UNKNOWN'}:
            raise ValueError('Outcome must be terminal in canonical graph')
        attempts = [snapshot.node(e.target) for e in snapshot.edges_from(action_id, {'HAS_ATTEMPT'})]
        attempts = [a for a in attempts if a]
        if not attempts:
            raise ValueError('Action outcome has no provenance-backed execution attempt')
        if state == 'SUCCEEDED' and not any(a.get('execution_state') == 'SUCCEEDED' for a in attempts):
            raise ValueError('Success is not supported by a confirmed attempt')
        if state == 'FAILED' and not any(a.get('execution_state') == 'FAILED' for a in attempts):
            raise ValueError('Failure is not supported by a failed attempt')
        evidence = sorted(str(a['id']) for a in attempts)
        outcome = {'id': 'ROUTCOME-' + _digest([self.tenant, action_id, state, evidence])[:32].upper(),
                   'tenant_id': self.tenant, 'action_id': action_id, 'result': state,
                   'evidence_ids': evidence, 'verified_at': utcnow(),
                   'confidence': 'CONFIRMED' if state != 'UNKNOWN' else 'UNRESOLVED'}
        return self.store.save_outcome(outcome)
