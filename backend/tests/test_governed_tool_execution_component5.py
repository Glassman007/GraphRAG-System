"""Component 5 adversarial acceptance tests; no real external network or DB required."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.app.agent_runtime.governed import (ActionProposal, ConnectorRegistry,
    GovernedActions, Decision, TOOLS)
from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot
from backend.app.api_v1 import router as api_router
from backend.app.main import app

CHANGE = 'CHG-AST-ROLLBACK'
INC = 'INC-AST-OUTAGE'
EVIDENCE = 'EVD-AST-TRACE'
POLICY = 'POL-AST-ROLLBACK'


def graph():
    nodes = {
        CHANGE:{'id':CHANGE,'_labels':['Entity','Change'],'status':'DEPLOYED'},
        INC:{'id':INC,'_labels':['Entity','Incident'],'status':'OPEN'},
        EVIDENCE:{'id':EVIDENCE,'_labels':['Entity','Evidence'],'status':'VERIFIED','source_ref_id':'TRACE-001'},
        POLICY:{'id':POLICY,'_labels':['Entity','Policy'],'effect':'ALLOW','policy_version':'1','action_type':'deployment_rollback','authoritative':True},
    }
    edges = [GraphEdge(EVIDENCE,'ABOUT',CHANGE,{}), GraphEdge(POLICY,'GOVERNS',CHANGE,{}),
             GraphEdge(CHANGE,'AFFECTS',INC,{})]
    return GraphSnapshot(nodes,edges)


class Store:
    def __init__(self):
        self.items = {}; self.audit={}; self.lock=threading.RLock()
    def get(self,id):
        with self.lock:return copy.deepcopy(self.items.get(id))
    def create(self,a):
        with self.lock:
            self.items.setdefault(a['id'],copy.deepcopy(a))
            self.audit.setdefault(a['id'],[{'type':'PROPOSED','action_id':a['id'],'actor':a['initiator']}])
            return copy.deepcopy(self.items[a['id']])
    def transition(self,old,new,event):
        with self.lock:
            actual = self.items.get(old['id'])
            if actual['revision'] != old['revision'] or actual['status'] != old['status']:
                raise RuntimeError('Concurrent action state transition')
            self.items[old['id']] = copy.deepcopy(new)
            self.audit[old['id']].append(copy.deepcopy(event))
            return copy.deepcopy(new)
    def events(self,id):
        with self.lock: return copy.deepcopy(self.audit.get(id,[]))


class Adapter:
    def __init__(self):self.calls=[];self.observed={};self.error=None;self.lock=threading.Lock()
    def invoke(self,*,operation_key,payload):
        with self.lock:
            self.calls.append((operation_key,payload))
        if self.error:raise self.error
        return {'receipt_id':'ACK-1','operation_id':'OP-1','acknowledged':True}
    def lookup(self,*,operation_key):return self.observed.get(operation_key)


@pytest.fixture
def rig():
    state=[graph()]
    store=Store(); adapter=Adapter()
    service=GovernedActions(store=store,snapshot_factory=lambda:state[0],tenant='asteria',
                            connectors=ConnectorRegistry({'DEPLOYMENT_ROLLBACK':adapter}),
                            run_lookup=lambda run_id: None)
    return service,store,adapter,state


def proposal(key='unique-example-key-001',supervisor_run_id=None, evidence=None):
    return ActionProposal(tool_id='deployment_rollback',target_id=CHANGE,
                          evidence_ids=evidence or [EVIDENCE],
                          arguments={'change_id':CHANGE,'reason':'New traces link rollout to outage'},
                          rationale='Rollback candidate based on verified trace evidence from outage',
                          agent_id='remediation_specialist' if supervisor_run_id else 'manual_operator',supervisor_run_id=supervisor_run_id,
                          idempotency_key=key)


def staged(rig):
    service,_,_,_=rig
    p=service.propose(proposal(),subject='operator')
    assert p['status']=='PROPOSED'
    p=service.request_approval(p['id'],subject='operator')
    assert p['status']=='PENDING_APPROVAL'
    p=service.decide(p['id'],subject='approver',approve=True,
                     reason='Verified need for controlled rollback',approver_permissions=frozenset({'APPROVE_ACTION'}))
    return p


def test_valid_graph_proposal_has_policy_provenance_and_simulation(rig):
    svc,store,_,_=rig
    p=svc.propose(proposal(),subject='operator')
    assert p['proposal_validation']['allowed']
    assert p['simulation']['non_mutating']
    assert graph().node(CHANGE)['status']=='DEPLOYED'
    assert store.events(p['id'])[0]['type']=='PROPOSED'
    assert p['approval'] is None


def test_duplicate_idempotency_key_is_stable_and_payload_change_denied(rig):
    svc,_,_,_=rig
    first=svc.propose(proposal(),subject='operator')
    assert svc.propose(proposal(),subject='operator')['id']==first['id']
    modified=proposal();modified.arguments['reason']='Different proposed recovery strategy'
    with pytest.raises(ValueError,match='Idempotency key reused'):
        svc.propose(modified,subject='operator')


def test_registry_is_allowlisted_and_unconfigured_tools_stay_off(rig):
    svc,_,_,_=rig
    assert {x['id'] for x in svc.connectors.list_tools()}==set(TOOLS)
    with pytest.raises(ValueError,match='allowlist'):
        svc.propose(proposal().model_copy(update={'tool_id':'shell_command'}),subject='operator')
    assert len(ConnectorRegistry(adapters={}).list_tools())==2
    assert all(not x['configured'] for x in ConnectorRegistry(adapters={}).list_tools())


def test_disconnected_evidence_unverified_and_missing_provenance_block(rig):
    svc,_,_,state=rig
    state[0].edges=[];state[0]=GraphSnapshot(state[0].nodes,state[0].edges)
    p=svc.propose(proposal(),subject='operator')
    assert not p['proposal_validation']['allowed']
    with pytest.raises(ValueError):svc.request_approval(p['id'],subject='operator')
    state[0]=graph();state[0].nodes[EVIDENCE]['confidence']='PROBABLE'
    p2=svc.propose(proposal('other-distinct-key-123'),subject='operator')
    assert 'EVIDENCE_NOT_VERIFIED:'+EVIDENCE in p2['proposal_validation']['violations']
    state[0]=graph();state[0].nodes[EVIDENCE].pop('source_ref_id')
    p3=svc.propose(proposal('third-distinct-key-123'),subject='operator')
    assert 'EVIDENCE_NO_SOURCE_PROVENANCE:'+EVIDENCE in p3['proposal_validation']['violations']


def test_missing_policy_and_explicit_deny_fail_closed(rig):
    svc,_,_,state=rig
    state[0].nodes.pop(POLICY);state[0]=GraphSnapshot(state[0].nodes,[x for x in state[0].edges if x.source!=POLICY])
    p=svc.propose(proposal(),subject='operator')
    assert 'NO_APPLICABLE_POLICY' in p['proposal_validation']['violations']
    with pytest.raises(ValueError):svc.request_approval(p['id'],subject='operator')
    state[0]=graph();state[0].nodes[POLICY]['effect']='DENY'
    p=svc.propose(proposal('deny-distinct-key-1234'),subject='operator')
    assert 'EXPLICIT_POLICY_DENY' in p['proposal_validation']['violations']


def test_two_person_approval_cannot_be_self_approved_or_spoofed(rig):
    svc,_,_,_=rig
    p=svc.propose(proposal(),subject='operator')
    svc.request_approval(p['id'],subject='operator')
    with pytest.raises(PermissionError,match='APPROVE_ACTION'):
        svc.decide(p['id'],subject='fake',approve=True,reason='Approved by AI agent',approver_permissions=frozenset())
    with pytest.raises(PermissionError,match='Separation'):
        svc.decide(p['id'],subject='operator',approve=True,reason='Self approval attempted',approver_permissions=frozenset({'APPROVE_ACTION'}))
    with pytest.raises(PermissionError,match='Separation'):
        svc.decide(p['id'],subject='manual_operator',approve=True,reason='Agent attempts self approval',approver_permissions=frozenset({'ADMIN'}))
    assert svc.detail(p['id'])['action']['status']=='PENDING_APPROVAL'


def test_rejection_is_terminal_and_cannot_execute(rig):
    svc,_,adapter,_=rig
    p=svc.propose(proposal(),subject='operator')
    svc.request_approval(p['id'],subject='operator')
    svc.decide(p['id'],subject='approver',approve=False,reason='Not a justified operational risk',approver_permissions=frozenset({'APPROVE_ACTION'}))
    with pytest.raises(ValueError):svc.execute(p['id'],subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)
    assert not adapter.calls


def test_stale_graph_after_approval_blocks_dispatch(rig):
    svc,_,adapter,state=rig
    p=staged(rig)
    state[0].nodes[EVIDENCE]['status']='INVALIDATED'
    result=svc.execute(p['id'],subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)
    assert result['status']=='STALE_PRECONDITION'
    assert adapter.calls==[]


def test_mutated_policy_content_requires_fresh_approval(rig):
    svc,_,adapter,state=rig
    p=staged(rig)
    state[0].nodes[POLICY]['description']='Version with new compliance language'
    result=svc.execute(p['id'],subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)
    assert result['status']=='STALE_PRECONDITION' and adapter.calls==[]


def test_one_execution_even_for_replayed_and_concurrent_requests(rig):
    svc,store,adapter,_=rig
    p=staged(rig)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(lambda _: run_safe(svc,p['id']), range(6)))
    assert len(adapter.calls)==1
    assert store.get(p['id'])['status']=='AWAITING_VERIFICATION'
    assert len([event for event in store.events(p['id']) if event['type']=='EXECUTION_CLAIMED'])==1
    assert svc.execute(p['id'],subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)['status']=='AWAITING_VERIFICATION'
    assert len(adapter.calls)==1
    assert any(x in {'AWAITING_VERIFICATION','EXECUTING','CONFLICT'} for x in results)


def run_safe(svc,action_id):
    try:return svc.execute(action_id,subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)['status']
    except RuntimeError:return 'CONFLICT'


def test_network_failure_unknown_and_no_automatic_retry(rig):
    svc,_,adapter,_=rig
    p=staged(rig)
    adapter.error=TimeoutError('remote write acknowledgment timed out')
    response=svc.execute(p['id'],subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)
    assert response['status']=='OUTCOME_UNKNOWN'
    svc.execute(p['id'],subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)
    assert len(adapter.calls)==1
    assert svc.verify(p['id'],subject='operator')['status']=='OUTCOME_UNKNOWN'


def test_verified_remote_readback_required_for_completion(rig):
    svc,_,adapter,_=rig
    p=staged(rig)
    result=svc.execute(p['id'],subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)
    op=result['execution']['operation_key']
    assert svc.verify(p['id'],subject='operator')['status']=='AWAITING_VERIFICATION'
    adapter.observed[op]={'status':'SUCCEEDED','receipt_id':'VERIFIED-RECEIPT-1'}
    finished=svc.verify(p['id'],subject='operator')
    assert finished['status']=='COMPLETED'
    assert finished['post_action_verification']['source']=='CONNECTOR_READBACK'
    assert [e['type'] for e in svc.detail(p['id'])['audit']][-1]=='POST_ACTION_VERIFIED'


def test_supervisor_run_unverified_citations_are_not_action_authority(rig):
    svc,_,_,_=rig
    svc.run_lookup=lambda _: {'status':'COMPLETED', 'subject':'operator','citations':[EVIDENCE], 'tasks':[], 'escalations':[], 'conflicts':[]}
    with pytest.raises(ValueError, match='corroborate'):
        svc.propose(proposal(supervisor_run_id='SRUN-1'),subject='operator')
    svc.run_lookup=lambda _: {'status':'COMPLETED','subject':'operator','citations':[EVIDENCE], 'source_entity_id':INC,
           'tasks':[{'capability':'verification','status':'COMPLETED','result':{'confidence':'supported','citations':[EVIDENCE]}},
                    {'capability':'remediation_proposal','status':'COMPLETED','agent_id':'remediation_specialist'}],
           'escalations':[],'conflicts':[]}
    p=svc.propose(proposal(supervisor_run_id='SRUN-1'),subject='operator')
    assert p['supervisor_run_id']=='SRUN-1'


def test_tenant_boundary_and_connector_unavailable(rig):
    svc,store,adapter,state=rig
    p=staged(rig)
    other=GovernedActions(store=store,snapshot_factory=lambda:state[0],tenant='other',connectors=svc.connectors)
    with pytest.raises(LookupError):other.detail(p['id'])
    svc.connectors.adapters={}
    with pytest.raises(ValueError,match='disabled'):
        svc.execute(p['id'],subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)
    assert adapter.calls==[]


def test_api_operator_cannot_approve_even_if_endpoint_called(monkeypatch,rig):
    svc,store,_,_=rig
    monkeypatch.setattr(api_router,'_governed',lambda principal:svc)
    client=TestClient(app)
    operator={'Authorization':'Bearer test-operator-token'}
    admin={'Authorization':'Bearer test-admin-token'}
    body=proposal().model_dump()
    response=client.post('/api/v1/agent-runtime/governed/actions',json=body,headers=operator)
    assert response.status_code==201,response.text
    aid=response.json()['id']
    # Route permissions come from authenticated token; passing a fake agent_id does not grant approval.
    response=client.post('/api/v1/agent-runtime/governed/actions/'+aid+'/request-approval',headers=operator)
    assert response.status_code==200,response.text
    denied=client.post('/api/v1/agent-runtime/governed/actions/'+aid+'/approve',
                       json={'reason':'AI agent believes action is safe'},headers=operator)
    assert denied.status_code==403
    approved=client.post('/api/v1/agent-runtime/governed/actions/'+aid+'/approve',
                         json={'reason':'Independently checked blast radius'},headers=admin)
    assert approved.status_code==200,approved.text
    assert approved.json()['status']=='APPROVED'


def test_unknown_outcome_can_be_escalated_without_reinvoking(rig):
    svc,store,adapter,_=rig
    p=staged(rig)
    adapter.error=TimeoutError('unconfirmed remote operation')
    result=svc.execute(p['id'],subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)
    escalated=svc.escalate(p['id'],subject='operator',reason='Request independent incident commander review',
                           permissions=frozenset({'EXECUTE_ACTION'}))
    assert escalated['status']=='OUTCOME_UNKNOWN' and escalated['escalation']['requires_human_review']
    assert svc.escalate(p['id'],subject='operator',reason='Duplicate escalation request',
                        permissions=frozenset({'EXECUTE_ACTION'}))['revision']==escalated['revision']
    assert len(adapter.calls)==1
    assert store.events(p['id'])[-1]['type']=='HUMAN_ESCALATION_REQUESTED'


def test_verified_failure_is_not_treated_as_success_or_retried(rig):
    svc,store,adapter,_=rig
    p=staged(rig)
    pending=svc.execute(p['id'],subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)
    key=pending['execution']['operation_key']
    adapter.observed[key]={'status':'FAILED','receipt_id':'FAILURE-001'}
    result=svc.verify(p['id'],subject='operator')
    assert result['status']=='FAILED'
    assert result['post_action_verification']['verified'] is False
    assert svc._proven_outcome(result)['result']=='FAILED'
    with pytest.raises(ValueError):svc.execute(p['id'],subject='operator',permissions=frozenset({'EXECUTE_ACTION'}),confirmed=True)
    assert len(adapter.calls)==1


def test_supervisor_owner_is_required_for_agent_attribution(rig):
    svc,_,_,_=rig
    svc.run_lookup=lambda _: {'status':'COMPLETED','subject':'unrelated-user','citations':[EVIDENCE],
         'tasks':[{'capability':'verification','status':'COMPLETED','result':{'confidence':'supported','citations':[EVIDENCE]}},
                  {'capability':'remediation_proposal','status':'COMPLETED','agent_id':'remediation_specialist'}],
         'escalations':[],'conflicts':[]}
    with pytest.raises(ValueError,match='Completed, unconflicted'):
        svc.propose(proposal(supervisor_run_id='SRUN-OTHER'),subject='operator')
    with pytest.raises(ValueError,match='Agent attribution'):
        svc.propose(proposal().model_copy(update={'agent_id':'remediation_specialist'}),subject='operator')


def test_non_authoritative_allow_policy_not_execution_authority(rig):
    svc,_,_,state=rig
    state[0].nodes[POLICY]['authoritative']=False
    p=svc.propose(proposal(),subject='operator')
    assert 'NO_EXPLICIT_ALLOW_POLICY' in p['proposal_validation']['violations']
    with pytest.raises(ValueError):svc.request_approval(p['id'],subject='operator')


def test_authoritative_policy_can_require_named_approver_and_role(rig):
    svc,_,_,state=rig
    state[0].nodes[POLICY]['required_approver']='incident-commander'
    state[0].nodes[POLICY]['required_approver_role']='CHANGE_APPROVER'
    p=svc.propose(proposal(),subject='operator')
    svc.request_approval(p['id'],subject='operator')
    with pytest.raises(PermissionError,match='named approver'):
        svc.decide(p['id'],subject='approver',approve=True,reason='Want to approve action',
                   approver_permissions=frozenset({'APPROVE_ACTION'}),approver_roles=('CHANGE_APPROVER',))
    with pytest.raises(PermissionError,match='approver role'):
        svc.decide(p['id'],subject='incident-commander',approve=True,reason='Authority checked for rollback',
                   approver_permissions=frozenset({'APPROVE_ACTION'}),approver_roles=('OPERATOR',))
    approved=svc.decide(p['id'],subject='incident-commander',approve=True,
                        reason='Independent rollback review complete',
                        approver_permissions=frozenset({'APPROVE_ACTION'}),approver_roles=('CHANGE_APPROVER',))
    assert approved['status']=='APPROVED'
