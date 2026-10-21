"""Component 5: fail-closed, evidence-grounded governed tool execution.

This subsystem NEVER interprets an agent recommendation as executable authority.
Real connectors are disabled until explicitly configured by the deployment owner.
An interrupted/ambiguous invocation is not replayed automatically.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import socket
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from backend.app.agent_runtime.tools import current
from backend.app.services.phase4_graph import GraphSnapshot, has_label


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class RollbackArgs(Strict):
    change_id: str = Field(min_length=3, max_length=150)
    reason: str = Field(min_length=12, max_length=500)


class NotificationArgs(Strict):
    incident_id: str = Field(min_length=3, max_length=150)
    message: str = Field(min_length=12, max_length=900)


class ActionProposal(Strict):
    tool_id: str
    target_id: str = Field(min_length=3, max_length=150)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    arguments: dict[str, Any]
    rationale: str = Field(min_length=20, max_length=1400)
    agent_id: str = Field(min_length=2, max_length=100)
    supervisor_run_id: str | None = Field(default=None, max_length=100)
    idempotency_key: str = Field(min_length=12, max_length=128)


class Decision(Strict):
    reason: str = Field(min_length=12, max_length=600)


class Execution(Strict):
    # Prevent API caller from substituting arbitrary payload/connector/approval fields.
    acknowledge_external_side_effect: bool


class VerifyOutcome(Strict):
    # Manual assertion cannot override connector-observed proof.
    reason: str = Field(min_length=12, max_length=600)


RISK_CLASSES = {
    'READ_ONLY': 'Pure graph reads; governed action execution is not needed',
    'REVERSIBLE': 'Side-effectful operations with an explicit recovery path; independent approval required',
    'HIGH_IMPACT': 'Consequential operational changes; independent approval and fresh evidence required',
    'IRREVERSIBLE': 'Disabled: no irreversible connector is registered for autonomous execution',
}

TOOLS = {
    'deployment_rollback': {'title': 'Rollback a deployment', 'risk': 'HIGH_IMPACT',
                            'arg_schema': RollbackArgs, 'connector_key': 'DEPLOYMENT_ROLLBACK',
                            'target_label': 'Change', 'approval_required': True,
                            'side_effect': 'Deployment rollback requested through configured HTTPS receiver'},
    'incident_notification': {'title': 'Notify incident responders', 'risk': 'REVERSIBLE',
                              'arg_schema': NotificationArgs, 'connector_key': 'INCIDENT_NOTIFICATION',
                              'target_label': 'Incident', 'approval_required': True,
                              'side_effect': 'Message delivered to configured HTTPS receiver'},
}


class ActionStore(Protocol):
    def create(self, action: dict) -> dict: ...
    def get(self, action_id: str) -> dict | None: ...
    def transition(self, previous: dict, updated: dict, event: dict) -> dict: ...
    def events(self, action_id: str) -> list[dict]: ...


class Connector(Protocol):
    def invoke(self, *, operation_key: str, payload: dict) -> dict: ...
    def lookup(self, *, operation_key: str) -> dict | None: ...


class WebhookConnector:
    """Deployment-operator-configured, server-side HTTPS-only connector.

    Uses a fixed URL from environment; never accepts a URL in a model proposal.
    Repeats are forbidden unless destination supplies a definitive operation receipt.
    """

    def __init__(self, *, url: str, token: str, status_url: str = ""):
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or
                parsed.query or parsed.fragment or parsed.port not in (None,443) or not token or len(token) < 12):
            raise ValueError('Connector needs a fixed HTTPS endpoint and a configured secret')
        # Fail closed for hostnames resolving to non-public addresses and raw private IPs.
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(info[4][0]).is_global for info in addresses):
            raise ValueError('Connector hostname must resolve only to public addresses')
        if status_url:
            status_parts = urlsplit(status_url)
            if (status_parts.scheme != 'https' or status_parts.hostname != parsed.hostname or
                    status_parts.port != parsed.port or status_parts.username or status_parts.password or
                    status_parts.query or status_parts.fragment):
                raise ValueError('Readback URL must have the same fixed HTTPS origin')
        self.url, self.token, self.status_url = url, token, status_url

    def invoke(self, *, operation_key: str, payload: dict) -> dict:
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode('utf-8'), method='POST',
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+self.token,
                     'Idempotency-Key': operation_key})
        # Redirects are forbidden: do not send a bearer token to a redirected host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=8) as response:
            data = json.loads(response.read(32768).decode('utf-8'))
            # ACK is not verification: the receiver must give an operation id and receipt.
            if not isinstance(data, dict) or not data.get('operation_id') or not data.get('receipt_id'):
                raise RuntimeError('Receiver gave no trustworthy idempotent operation receipt')
            return {'operation_id': str(data['operation_id'])[:180],
                    'receipt_id': str(data['receipt_id'])[:180], 'acknowledged': True,
                    'reported_status': str(data.get('status') or 'ACCEPTED')[:80]}

    def lookup(self, *, operation_key: str) -> dict | None:
        if not self.status_url:
            return None
        # Authenticated read-only GET, no redirect and no externally specified URI.
        key = operation_key  # SHA-256 lowercase hex generated internally
        if len(key) != 64 or any(x not in '0123456789abcdef' for x in key):
            raise ValueError('Invalid operation key')
        request = urllib.request.Request(self.status_url.rstrip('/')+'/'+key,method='GET',
                                         headers={'Authorization':'Bearer '+self.token})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=8) as response:
            data = json.loads(response.read(32768).decode('utf-8'))
            if not isinstance(data,dict) or data.get('operation_key') != key:
                raise RuntimeError('Readback key mismatch')
            if data.get('status') not in {'SUCCEEDED','FAILED'} or not data.get('receipt_id'):
                return None
            return {'status':data['status'], 'receipt_id':str(data['receipt_id'])[:180],
                    'operation_key':key,'verified_external':True}


class ConnectorRegistry:
    def __init__(self, adapters: dict[str, Connector] | None = None):
        self.adapters = adapters if adapters is not None else self._from_environment()

    @staticmethod
    def _from_environment() -> dict[str, Connector]:
        adapters = {}
        for spec in TOOLS.values():
            key = spec['connector_key']
            url, token = os.getenv('GRAPH_HACKS_GOVERNED_'+key+'_URL', ''), os.getenv('GRAPH_HACKS_GOVERNED_'+key+'_TOKEN', '')
            if url and token:
                adapters[key] = WebhookConnector(url=url, token=token,
                    status_url=os.getenv('GRAPH_HACKS_GOVERNED_'+key+'_STATUS_URL',''))
        return adapters

    def list_tools(self) -> list[dict]:
        return [{k: v for k, v in spec.items() if k != 'arg_schema'} |
                {'id': name, 'schema': spec['arg_schema'].model_json_schema(),
                 'configured': spec['connector_key'] in self.adapters}
                for name, spec in TOOLS.items()]


class GovernedActions:
    def __init__(self, *, store: ActionStore, snapshot_factory: Callable[[], GraphSnapshot],
                 tenant: str, connectors: ConnectorRegistry | None = None,
                 run_lookup: Callable[[str], dict | None] | None = None,
                 outcome_sink: Callable[[dict], dict] | None = None):
        self.store, self.snapshot_factory, self.tenant = store, snapshot_factory, tenant
        self.connectors = connectors if connectors is not None else ConnectorRegistry()
        self.run_lookup = run_lookup
        self.outcome_sink = outcome_sink

    def _load(self, action_id: str) -> dict:
        action = self.store.get(action_id)
        if not action or action['tenant_id'] != self.tenant:
            raise LookupError('Governed action not found')
        return action

    @staticmethod
    def _evidence_related(snapshot: GraphSnapshot, evidence_id: str, target_id: str) -> bool:
        # Graph attachment must be explicit, not just an arbitrary active evidence ID.
        # One intermediate Incident/System/Change is allowed for a path of length two.
        frontier = {evidence_id}
        for _ in range(2):
            next_frontier = set()
            for entity_id in frontier:
                for other, edge, _ in snapshot.neighbors(entity_id, {'ABOUT', 'EVIDENCED_BY', 'SUPPORTS', 'AFFECTS',
                                                                      'CHANGED', 'DERIVED_FROM', 'REFUTES'}):
                    if not snapshot._edge_active(edge, None):
                        continue
                    if other == target_id:
                        return True
                    next_frontier.add(other)
            frontier = next_frontier
        return False

    def _guard(self, action: dict, snapshot: GraphSnapshot) -> dict:
        tool = TOOLS[action['tool_id']]
        target_id = action['target_id']
        target = snapshot.node(target_id)
        violations = []
        if not has_label(target, tool['target_label']) or not current(target):
            violations.append('TARGET_NOT_CURRENT_OR_WRONG_TYPE')
        evidence = []
        for eid in action['evidence_ids']:
            node = snapshot.node(eid)
            if not has_label(node, 'Evidence') or not current(node) or str((node or {}).get('status') or '').upper() in {'INVALID','INVALIDATED','REJECTED','MISSING','SUPERSEDED','DRAFT','UNVERIFIED','REVIEW_REQUIRED','CONTRADICTED'}:
                violations.append('EVIDENCE_INVALID:'+eid)
            elif str(node.get('confidence') or '').upper() in {'PROBABLE','UNVERIFIED','CONTRADICTED'}:
                violations.append('EVIDENCE_NOT_VERIFIED:'+eid)
            elif not node.get('source_ref_id') and not snapshot.edges_from(eid, {'DERIVED_FROM'}):
                violations.append('EVIDENCE_NO_SOURCE_PROVENANCE:'+eid)
            elif not self._evidence_related(snapshot, eid, target_id):
                violations.append('EVIDENCE_NOT_LINKED_TO_TARGET:'+eid)
            else:
                evidence.append({'id': eid, 'status': node.get('status'), 'source_ref_id': node.get('source_ref_id'),
                                 'valid_until': node.get('valid_until'), 'revision': node.get('revision'),
                                 'content_hash': digest({k:v for k,v in node.items() if k not in
                                  {'updated_at','ingested_at','recorded_at','last_seen_at'}})})
        policies = []
        applicable = {target_id}
        for edge in snapshot.neighbors(target_id, {'CHANGED', 'AFFECTS', 'ABOUT'}, direction='both'):
            applicable.add(edge[0])
        for entity_id in sorted(applicable):
            for edge in snapshot.edges_to(entity_id, {'GOVERNS'}):
                node = snapshot.node(edge.source)
                if (not has_label(node, 'Policy') or not current(node) or
                        str((node or {}).get('status') or '').upper() in {'DISABLED','INVALIDATED','REVOKED','DRAFT'}):
                    continue
                policy = {'id': edge.source, 'effect': str(node.get('effect') or node.get('decision') or '').upper(),
                          'version': str(node.get('policy_version') or node.get('version') or ''),
                          'authoritative': bool(node.get('authoritative') or edge.properties.get('authoritative')),
                          'status': str(node.get('status') or ''), 'target': entity_id,
                          'action_type': str(node.get('action_type') or ''),
                          'required_approver': str(node.get('required_approver') or ''),
                          'required_approver_role': str(node.get('required_approver_role') or ''),
                          'content_hash':digest({k:v for k,v in node.items() if k not in
                           {'updated_at','ingested_at','recorded_at','last_seen_at'}})}
                # Empty policy action_type applies to all; scoped mismatches are excluded.
                if policy['action_type'] and policy['action_type'] != action['tool_id']:
                    continue
                policies.append(policy)
        if not policies:
            violations.append('NO_APPLICABLE_POLICY')
        if any(p['effect'] in {'DENY','PROHIBIT','PROHIBITED','BLOCK'} for p in policies):
            violations.append('EXPLICIT_POLICY_DENY')
        if not any(p['authoritative'] and p['effect'] in {'ALLOW','PERMIT'} for p in policies):
            violations.append('NO_EXPLICIT_ALLOW_POLICY')
        # Current graph fingerprint deliberately excludes volatile ingestion bookkeeping.
        guard_material = {'target': {k: (target or {}).get(k) for k in
                                      ('id','status','revision','valid_from','valid_until','owner_id','policy_version','severity','criticality')},
                          'target_relations': sorted((e.source,e.type,e.target,digest(e.properties)) for e in snapshot.edges
                                                     if (e.source in applicable or e.target in applicable) and
                                                     e.type in {'GOVERNS','AFFECTS','CHANGED','ABOUT','EVIDENCED_BY','SUPPORTS','REFUTES'}
                                                     and snapshot._edge_active(e,None)),
                          'evidence': evidence, 'policies': policies}
        return {'allowed': not violations, 'violations': sorted(set(violations)),
                'policies': policies, 'evidence': evidence, 'fingerprint': digest(guard_material)}

    def simulate(self, action: dict, snapshot: GraphSnapshot) -> dict:
        tool_id, target_id = action['tool_id'], action['target_id']
        # Existing pure blast radius reasoning; never modifies canonical graph.
        from backend.app.services.simulation_service import CounterfactualSimulationService
        baseline = CounterfactualSimulationService._blast(snapshot, target_id, max_depth=4)
        hypothetical = snapshot.clone()
        operations = []
        if tool_id == 'deployment_rollback':
            operations.append(CounterfactualSimulationService._apply(hypothetical, {
                'op': 'rollback_change', 'change_id': action['arguments']['change_id']}))
        changed = CounterfactualSimulationService._blast(hypothetical, target_id, max_depth=4)
        return {'non_mutating': True, 'baseline': baseline, 'counterfactual': changed,
                'operations': operations, 'scope_limit': 'Graph-only simulation; does not predict real production outcomes'}

    @staticmethod
    def _event(action: dict, kind: str, actor: str, details: dict) -> dict:
        # Audits are immutable graph event records, not mutable application logs.
        return {'id': 'GAUD-'+uuid.uuid4().hex.upper(), 'action_id': action['id'],
                'tenant_id': action['tenant_id'], 'actor': actor, 'type': kind,
                'occurred_at': now(), 'details': details, 'revision': action['revision']}

    def propose(self, proposal: ActionProposal, *, subject: str) -> dict:
        if proposal.tool_id not in TOOLS:
            raise ValueError('Tool not on governed allowlist')
        if len(proposal.evidence_ids) != len(set(proposal.evidence_ids)):
            raise ValueError('Evidence IDs must be distinct')
        spec = TOOLS[proposal.tool_id]
        args = spec['arg_schema'].model_validate(proposal.arguments).model_dump()
        if args.get('change_id', args.get('incident_id')) != proposal.target_id:
            raise ValueError('Target and tool arguments must describe the same entity')
        if not proposal.supervisor_run_id and proposal.agent_id != 'manual_operator':
            raise ValueError('Agent attribution requires a validated supervisor run; use manual_operator for human proposals')
        if proposal.supervisor_run_id:
            if self.run_lookup is None:
                raise ValueError('Supervisor verification unavailable')
            run = self.run_lookup(proposal.supervisor_run_id)
            if (not run or run.get('subject') != subject or str(run.get('status')) != 'COMPLETED' or
                    run.get('escalations') or run.get('conflicts')):
                raise ValueError('Completed, unconflicted supervisor run required')
            verifier_tasks = [task for task in run.get('tasks') or []
                              if task.get('capability') == 'verification' and task.get('status') == 'COMPLETED'
                              and (task.get('result') or {}).get('confidence') == 'supported']
            remediation_tasks = [task for task in run.get('tasks') or []
                                 if task.get('capability') == 'remediation_proposal' and
                                 task.get('status') == 'COMPLETED' and task.get('agent_id') == proposal.agent_id]
            cited = set(run.get('citations') or [])
            cited.update(e for task in verifier_tasks for e in (task.get('result') or {}).get('citations') or [])
            if (not verifier_tasks or not remediation_tasks or
                    not set(proposal.evidence_ids).issubset(cited)):
                raise ValueError('Supervisor remediation/verification did not corroborate provided citations')
            source = str(run.get('source_entity_id') or '')
            snapshot = self.snapshot_factory()
            if source and proposal.target_id != source and not any(
                    e.target == proposal.target_id or e.source == proposal.target_id
                    for e in snapshot.edges if e.source == source or e.target == source):
                raise ValueError('Action target is not connected to supervisor objective')
        stable = {'tool_id': proposal.tool_id, 'target_id': proposal.target_id,
                  'arguments': args, 'evidence_ids': sorted(proposal.evidence_ids),
                  'rationale': proposal.rationale, 'agent_id': proposal.agent_id,
                  'supervisor_run_id': proposal.supervisor_run_id, 'initiator': subject}
        action_id = 'GACT-'+digest([self.tenant,subject,proposal.idempotency_key])[:32].upper()
        action = {'id':action_id, 'tenant_id':self.tenant, 'initiator':subject, 'agent_id':proposal.agent_id,
                  'supervisor_run_id':proposal.supervisor_run_id or '', 'tool_id':proposal.tool_id,
                  'target_id':proposal.target_id, 'arguments':args, 'evidence_ids':sorted(proposal.evidence_ids),
                  'rationale':proposal.rationale, 'risk':spec['risk'], 'side_effect':spec['side_effect'],
                  'status':'PROPOSED', 'revision':1, 'created_at':now(), 'updated_at':now(),
                  'request_digest':digest(stable), 'approval':None, 'execution':None,
                  'post_action_verification':None, 'failure':None}
        # Fail-closed: only a valid grounded graph proposal is persisted.
        snapshot = self.snapshot_factory()
        guard = self._guard(action,snapshot)
        action['proposal_validation'] = guard
        action['simulation'] = self.simulate(action,snapshot)
        saved = self.store.create(action)
        if saved['request_digest'] != action['request_digest'] or saved['initiator'] != subject:
            raise ValueError('Idempotency key reused with different proposal')
        return saved

    def request_approval(self, action_id: str, *, subject: str) -> dict:
        action = self._load(action_id)
        if action['initiator'] != subject:
            raise PermissionError('Only initiating principal may request approval')
        if action['status'] == 'PENDING_APPROVAL':
            return action
        if action['status'] != 'PROPOSED':
            raise ValueError('Action cannot request approval from this state')
        guard = self._guard(action,self.snapshot_factory())
        if not guard['allowed']:
            raise ValueError('Policy/evidence blocks request: '+', '.join(guard['violations']))
        updated = {**action, 'revision':action['revision']+1, 'status':'PENDING_APPROVAL',
                   'approval_requested_at':now(), 'preapproval_fingerprint':guard['fingerprint'], 'updated_at':now()}
        return self.store.transition(action,updated,self._event(updated,'APPROVAL_REQUESTED',subject,{'guard':guard}))

    def decide(self, action_id: str, *, subject: str, approve: bool, reason: str,
               approver_permissions: frozenset[str],
               approver_roles: tuple[str, ...] = ()) -> dict:
        if 'APPROVE_ACTION' not in approver_permissions and 'ADMIN' not in approver_permissions:
            raise PermissionError('APPROVE_ACTION permission required')
        action = self._load(action_id)
        if action['initiator'] == subject or action['agent_id'] == subject:
            raise PermissionError('Separation of duties: initiator or originating agent cannot self-approve')
        if action['status'] != 'PENDING_APPROVAL':
            raise ValueError('Only pending proposals may be decided')
        guard = self._guard(action,self.snapshot_factory())
        if approve:
            for policy in guard['policies']:
                if not policy['authoritative'] or policy['effect'] not in {'ALLOW','PERMIT'}:
                    continue
                if policy['required_approver'] and policy['required_approver'] != subject:
                    raise PermissionError('Applicable policy requires a different named approver')
                if policy['required_approver_role'] and policy['required_approver_role'] not in approver_roles:
                    raise PermissionError('Applicable policy requires a different approver role')
        if approve and (not guard['allowed'] or guard['fingerprint'] != action.get('preapproval_fingerprint')):
            raise ValueError('Policy or evidence changed; a new proposal/review is required')
        updated = {**action,'revision':action['revision']+1,
                   'status':'APPROVED' if approve else 'REJECTED', 'updated_at':now(),
                   'approval':{'actor':subject,'approved':approve,'reason':reason,'at':now(),
                               'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=30)).isoformat() if approve else None,
                               'fingerprint':guard['fingerprint']}}
        return self.store.transition(action,updated,self._event(updated,'APPROVED' if approve else 'REJECTED',subject,{'reason':reason, 'guard':guard}))

    def execute(self, action_id: str, *, subject: str, permissions: frozenset[str], confirmed: bool) -> dict:
        if not confirmed or ('EXECUTE_ACTION' not in permissions and 'ADMIN' not in permissions):
            raise PermissionError('Explicit execute confirmation and EXECUTE_ACTION permission required')
        action = self._load(action_id)
        if action['status'] in {'EXECUTING','COMPLETED','AWAITING_VERIFICATION','OUTCOME_UNKNOWN'}:
            # Read-only return; never duplicate an external call on replay.
            return action
        if action['status'] != 'APPROVED' or not action.get('approval',{}).get('approved'):
            raise ValueError('A separate, authorized human approval is required')
        approval = action['approval']
        if datetime.fromisoformat(approval['expires_at']) <= datetime.now(timezone.utc):
            raise ValueError('Approval expired')
        connector = self.connectors.adapters.get(TOOLS[action['tool_id']]['connector_key'])
        if connector is None:
            raise ValueError('External connector disabled by deployment policy')
        guard = self._guard(action,self.snapshot_factory())
        if not guard['allowed'] or guard['fingerprint'] != approval['fingerprint']:
            updated = {**action,'revision':action['revision']+1,'status':'STALE_PRECONDITION',
                       'failure':'Graph evidence or policy changed since approval', 'updated_at':now()}
            return self.store.transition(action,updated,self._event(updated,'PRECONDITION_DENIED',subject,{'guard':guard}))
        # CAS claim is durable before invoking. If process crashes, never auto-replay a
        # potentially executed non-idempotent operation without external reconciliation.
        op_key = digest([self.tenant,action['id'],action['request_digest']])
        updated = {**action,'revision':action['revision']+1,'status':'EXECUTING','updated_at':now(),
                   'execution':{'claimed_by':subject,'operation_key':op_key,'claimed_at':now(), 'attempt':1}}
        claimed = self.store.transition(action,updated,self._event(updated,'EXECUTION_CLAIMED',subject,{'operation_key':op_key}))
        # A second source read immediately before invocation reduces stale-approval risk.
        guard2 = self._guard(claimed,self.snapshot_factory())
        if not guard2['allowed'] or guard2['fingerprint'] != approval['fingerprint']:
            stale = {**claimed,'revision':claimed['revision']+1,'status':'STALE_PRECONDITION',
                     'failure':'Preconditions changed after dispatch claim','updated_at':now()}
            return self.store.transition(claimed,stale,self._event(stale,'EXECUTION_ABORTED',subject,{'guard':guard2}))
        try:
            receipt = connector.invoke(operation_key=op_key,
                payload={'action_id':action['id'], 'tenant_id':self.tenant, 'tool_id':action['tool_id'],
                         'target_id':action['target_id'], 'arguments':action['arguments'],
                         'approval':{'actor':approval['actor'],'at':approval['at']}})
        except Exception as exc:
            # An HTTP/network error does NOT establish whether the remote action happened.
            uncertain = {**claimed,'revision':claimed['revision']+1,'status':'OUTCOME_UNKNOWN',
                         'failure':f'{type(exc).__name__}: {str(exc)[:180]}', 'updated_at':now()}
            return self.store.transition(claimed,uncertain,self._event(uncertain,'OUTCOME_UNKNOWN',subject,{'error_type':type(exc).__name__}))
        awaiting = {**claimed,'revision':claimed['revision']+1,'status':'AWAITING_VERIFICATION',
                    'execution':{**claimed['execution'],'receipt':receipt, 'acknowledged_at':now()},'updated_at':now()}
        return self.store.transition(claimed,awaiting,self._event(awaiting,'CONNECTOR_ACKNOWLEDGED',subject,{'receipt':receipt}))

    def verify(self, action_id: str, *, subject: str) -> dict:
        action = self._load(action_id)
        if action['status'] not in {'AWAITING_VERIFICATION','OUTCOME_UNKNOWN','EXECUTING'}:
            raise ValueError('No pending remote action to verify')
        op_key = (action.get('execution') or {}).get('operation_key')
        connector = self.connectors.adapters.get(TOOLS[action['tool_id']]['connector_key'])
        if not op_key or connector is None:
            raise ValueError('No configured connector to retrieve external status')
        status = connector.lookup(operation_key=op_key)
        if not status or str(status.get('status')) not in {'SUCCEEDED','FAILED'} or not status.get('receipt_id'):
            # Keep unchanged; accepting user-asserted success would be unsafe.
            return action
        success = status['status'] == 'SUCCEEDED'
        updated = {**action,'revision':action['revision']+1,
                   'status':'COMPLETED' if success else 'FAILED', 'updated_at':now(),
                   'post_action_verification':{'at':now(),'verified_by':subject, 'connector_receipt':status,
                                                'verified':success,'source':'CONNECTOR_READBACK'}}
        persisted = self.store.transition(action,updated,self._event(updated,'POST_ACTION_VERIFIED',subject,{'observation':status}))
        if self.outcome_sink is not None:
            try:
                self.outcome_sink(self._proven_outcome(persisted))
            except Exception as exc:
                # Verified operation already happened; learning failure cannot roll it back.
                return {**persisted, 'learning_warning': 'Durable outcome capture needs retry: '+type(exc).__name__}
        return persisted

    @staticmethod
    def _proven_outcome(action: dict) -> dict:
        evidence = action.get('post_action_verification') or {}
        receipt = evidence.get('connector_receipt') or {}
        if (action['status'] not in {'COMPLETED','FAILED'} or
                evidence.get('source') != 'CONNECTOR_READBACK' or
                receipt.get('status') not in {'SUCCEEDED','FAILED'} or
                not receipt.get('receipt_id') or not (action.get('execution') or {}).get('operation_key')):
            raise ValueError('No independently confirmed connector result exists')
        result = 'SUCCEEDED' if action['status'] == 'COMPLETED' else 'FAILED'
        return {'id':'ROUTCOME-'+digest([action['tenant_id'],action['id'],result,receipt['receipt_id']])[:32].upper(),
                'tenant_id':action['tenant_id'], 'action_id':action['id'], 'result':result,
                'evidence_ids':action['evidence_ids'], 'tool_id':action['tool_id'],
                'target_id':action['target_id'], 'origin_agent_id':action['agent_id'],
                'origin_supervisor_run_id':action['supervisor_run_id'],
                'approval_actor':action['approval']['actor'], 'connector_receipt':receipt,
                'verified_at':evidence['at'], 'confidence':'CONFIRMED'}

    def learn_verified_outcome(self, action_id: str) -> dict:
        if self.outcome_sink is None:
            raise ValueError('Verified outcome storage not configured')
        return self.outcome_sink(self._proven_outcome(self._load(action_id)))

    def escalate(self, action_id: str, *, subject: str, reason: str,
                 permissions: frozenset[str]) -> dict:
        if not ({'EXECUTE_ACTION','APPROVE_ACTION','ADMIN'} & permissions):
            raise PermissionError('An authorized operator or approver must escalate')
        action = self._load(action_id)
        if action['status'] not in {'OUTCOME_UNKNOWN','FAILED','STALE_PRECONDITION'}:
            raise ValueError('Escalation is reserved for uncertain or failed operations')
        if action.get('escalation'):
            return action
        updated = {**action, 'revision':action['revision']+1, 'updated_at':now(),
                   'escalation':{'requested_by':subject,'at':now(), 'reason':reason,
                                 'requires_human_review':True}}
        return self.store.transition(action,updated,self._event(updated,'HUMAN_ESCALATION_REQUESTED',subject,
                                                               {'reason':reason,'status':updated['status']}))

    def detail(self, action_id: str) -> dict:
        action = self._load(action_id)
        return {'action':action, 'audit':self.store.events(action_id)}

    def preview(self, action_id: str) -> dict:
        action = self._load(action_id)
        snapshot = self.snapshot_factory()
        return {'action_id':action_id, 'current_authorization':self._guard(action,snapshot),
                'simulation':self.simulate(action,snapshot), 'status':action['status'],
                'connector_configured':TOOLS[action['tool_id']]['connector_key'] in self.connectors.adapters}
