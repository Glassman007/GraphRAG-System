"""Component 4: authoritative changes, idempotency, access, lineage and replan replay."""
from __future__ import annotations

import copy
import json
import threading

import pytest
from fastapi.testclient import TestClient

from backend.app.agent_runtime.reactive import ReactiveLearning, graph_delta
from backend.app.agent_runtime.memory import AgentMemory
from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot
from backend.tests.test_supervisor_component2 import graph, INCIDENT, Store, ScriptedProvider
from backend.tests.test_agent_memory_component3 import Backend as MemoryBackend, stage, promote, PERMS
from backend.app.agent_runtime.supervisor import Supervisor, SupervisorSettings
from backend.app.agent_runtime.tools import ToolRegistry

ROUTE = 'SYS-AST-DISPATCH'
DB = 'SYS-AST-DB'

class EventStore:
    """Explicitly in-memory test adapter, never used as persistence in production."""
    def __init__(self, mem):
        self.events = {}
        self.mem = mem
        self.versions = []
        self.checkpoints = {}
        self.outcomes = {}
        self.lock = threading.RLock()
    def enqueue(self, event):
        with self.lock:
            self.events.setdefault(event['id'], copy.deepcopy(event))
            return copy.deepcopy(self.events[event['id']])
    def claim(self):
        with self.lock:
            for e in self.events.values():
                if e['status'] in {'PENDING', 'RETRY'}:
                    e['status'] = 'PROCESSING'
                    return {**copy.deepcopy(e), 'lease_token': 'lease'}
        return None
    def finish(self, eid, *, token, result):
        with self.lock:
            self.events[eid].update(copy.deepcopy(result))
    def fail(self, eid, *, token, error):
        with self.lock:
            e = self.events[eid]
            e['attempts'] += 1
            e['status'] = 'RETRY' if e['attempts'] < 3 else 'FAILED_NEEDS_REVIEW'
            e['error'] = error
    def affected_memories(self, ids):
        with self.lock:
            return [copy.deepcopy(m) for m in self.mem.items.values() if
                    m['scope'] == 'SHARED' and m['status'] == 'VERIFIED' and
                    ({m['subject_id'],m['value']} | set(m['citations'])) & set(ids)]
    def affected_checkpoints(self, ids):
        with self.lock:
            return [copy.deepcopy(c) for c in self.checkpoints.values() if c.get('source') in ids or any(
                set((t.get('result') or {}).get('citations') or []) & set(ids) for t in c.get('tasks', []))]
    def revise_memory(self, old, new, *, event_id):
        with self.lock:
            assert old['tenant_id'] == new['tenant_id']
            current = self.mem.items[old['id']]
            if current['revision'] != old['revision']:
                raise RuntimeError('Conflict')
            self.versions.append({'type': 'memory', 'event_id': event_id, 'old': copy.deepcopy(old)})
            self.mem.items[old['id']] = copy.deepcopy(new)
    def revise_checkpoint(self, old, new, *, event_id):
        with self.lock:
            key = (old['owner'], old['id'])
            self.versions.append({'type': 'checkpoint', 'event_id': event_id, 'old': copy.deepcopy(old)})
            self.checkpoints[key] = copy.deepcopy(new)
    def save_outcome(self, outcome):
        self.outcomes.setdefault(outcome['id'], copy.deepcopy(outcome))
        return copy.deepcopy(self.outcomes[outcome['id']])


def services():
    mem_backend = MemoryBackend()
    current = [graph()]
    memory = AgentMemory(backend=mem_backend, snapshot_factory=lambda: current[0], tenant='asteria')
    store = EventStore(mem_backend)
    service = ReactiveLearning(store=store, memory=memory, snapshot_factory=lambda: current[0], tenant='asteria')
    return service, memory, store, current


def checkpoint(*, source=INCIDENT):
    return {'id': 'SRUN-'+'C'*32, 'tenant':'asteria', 'owner':'tester', 'status':'COMPLETED',
            'settings': SupervisorSettings(goal='Investigate incident dependency reliability', source_entity_id=INCIDENT,
                                            allow_external_model=True).model_dump(),
            'goal':'Investigate incident dependency reliability', 'source':source,
            'events':[], 'revision':4, 'tokens_used':200,
            'tasks':[{'id':'check_source','objective':'Read direct dependency evidence',
                      'capability':'dependency_analysis','depends_on':[], 'status':'COMPLETED',
                      'agent_id':'dependency_analyst','attempts':1,
                      'result':{'citations':[ROUTE,DB], 'confidence':'supported'}},
                     {'id':'unrelated','objective':'Inspect unrelated service records',
                      'capability':'evidence_retrieval','depends_on':[], 'status':'COMPLETED',
                      'agent_id':'evidence_retriever','attempts':1,
                      'result':{'citations':['EVD-OTHER'], 'confidence':'supported'}},
                     {'id':'verify','objective':'Verify the dependency investigation',
                      'capability':'verification','depends_on':['check_source'], 'status':'COMPLETED',
                      'agent_id':'policy_verifier','attempts':1,
                      'result':{'citations':['EVD-OTHER'],'confidence':'supported'}}]}


def publish_dependency_removed(service, current, *, authority='AUTHORITATIVE'):
    previous = current[0].clone()
    current[0].remove_edges(lambda e: e.type=='DEPENDS_ON' and e.source==ROUTE and e.target==DB)
    changes = graph_delta(previous,current[0],[ROUTE,DB])
    return service.publish(source_record_id='SRCREC-100', source_checksum='a123',
                           changes=changes, authority=authority, ingestion_run_id='ING-1', source_id='db-feed')


def test_change_detection_no_metadata_noise_or_duplicate_event():
    service, memory, store, current = services()
    before = current[0].clone()
    current[0].nodes[ROUTE]['updated_at']='2026-10-18T12:00:00Z'
    assert graph_delta(before,current[0],[ROUTE]) == []
    ev=publish_dependency_removed(service,current)
    assert ev['confidence']=='CONFIRMED' and ROUTE in ev['changed_ids']
    clone=copy.deepcopy(ev)
    assert store.enqueue(clone)==ev
    assert len(store.events)==1
    assert service.process(limit=10)[0]['status']=='COMPLETED'
    assert service.process(limit=10)==[]


def test_authoritative_change_stales_memory_preserves_history_and_replans_targeted_tasks():
    service, memory, store, current = services()
    stage(memory, run='first', branch='first:analyst')
    assert promote(memory, run='first')[0]['status']=='VERIFIED'
    cp=checkpoint()
    store.checkpoints[('tester',cp['id'])]=cp
    ev=publish_dependency_removed(service,current)
    outcomes=service.process()
    assert len(outcomes)==1
    effect=outcomes[0]
    assert len(effect['memory_impacts'])==1 and effect['memory_impacts'][0]['decision']=='STALE'
    assert effect['workflow_impacts'][0]['affected_task_ids']==['check_source','verify']
    # unrelated task was not erased or rescheduled
    newcp=store.checkpoints[('tester',cp['id'])]
    assert newcp['status']=='REPLAN_REQUIRED' and newcp['tasks'][1]['status']=='COMPLETED'
    assert newcp['revision']==5
    assert all(version['event_id']==ev['id'] for version in store.versions)
    assert len(store.versions)==2
    assert not memory.retrieve(requester='other',agent_id='investigator',permissions=PERMS,
         search=__import__('backend.app.agent_runtime.memory',fromlist=['MemorySearch']).MemorySearch(entity_ids=[ROUTE]))


def test_authoritative_change_still_supported_is_reverified_not_staled():
    service,memory,store,current=services()
    stage(memory,run='first',branch='first:analyst'); promote(memory,run='first')
    prev=current[0].clone()
    current[0].nodes[ROUTE]['status']='HEALTHY'
    event=service.publish(source_record_id='SRCREC-2',source_checksum='b2',
                          changes=graph_delta(prev,current[0],[ROUTE]),authority='AUTHORITATIVE',
                          ingestion_run_id='ING-2',source_id='test-source')
    result=service.process()[0]
    assert result['memory_impacts'][0]['decision']=='REVERIFIED'
    record=list(store.mem.items.values())[0]
    assert record['status']=='VERIFIED' and record['last_rechecked_by']=='reactive_graph_verifier'
    # Replay after a crash between a memory update and event acknowledgement must not revise twice.
    store.events[event['id']]['status']='PENDING'
    service.process()
    assert record['revision']==store.mem.items[record['id']]['revision']


def test_probable_changes_require_review_not_auto_invalidation():
    service,memory,store,current=services()
    stage(memory,run='first',branch='first:analyst'); promote(memory,run='first')
    event=publish_dependency_removed(service,current,authority='NON_AUTHORITATIVE')
    result=service.process()[0]
    assert result['status']=='NEEDS_REVIEW' and result['confidence']=='PROBABLE'
    assert result['memory_impacts']==[] and result['workflow_impacts']==[]
    assert list(store.mem.items.values())[0]['status']=='VERIFIED'


def test_source_scope_is_not_leaked_across_tenants():
    service,memory,store,current=services()
    old=stage(memory,run='first',branch='first:analyst'); promote(memory,run='first')
    copy_record=copy.deepcopy(store.mem.items[old['id']]); copy_record['id']='MEM-OTHER'; copy_record['tenant_id']='other'
    store.mem.items['MEM-OTHER']=copy_record
    publish_dependency_removed(service,current)
    service.process()
    assert store.mem.items['MEM-OTHER']['status']=='VERIFIED'


def test_failures_are_retried_then_dead_letter_without_fake_success():
    service,memory,store,current=services()
    publish_dependency_removed(service,current)
    def unavailable(*args,**kwargs): raise RuntimeError('FalkorDB unavailable')
    store.affected_memories=unavailable
    for attempt in range(3):
        assert service.process()==[]
    assert list(store.events.values())[0]['status']=='FAILED_NEEDS_REVIEW'


def test_action_outcomes_require_terminal_graph_proof():
    service,memory,store,current=services()
    with pytest.raises(ValueError,match='not found'):
        service.learn_action_outcome(action_id='ACT-NONE')
    current[0].nodes['ACT-1']={'id':'ACT-1','_labels':['Entity','Action'],'status':'SUCCEEDED'}
    with pytest.raises(ValueError,match='attempt'):
        service.learn_action_outcome(action_id='ACT-1')
    current[0].nodes['ATT-1']={'id':'ATT-1','_labels':['Entity','ActionAttempt'],'execution_state':'SUCCEEDED'}
    current[0].add_edge('ACT-1','HAS_ATTEMPT','ATT-1',{})
    result=service.learn_action_outcome(action_id='ACT-1')
    assert result['result']=='SUCCEEDED' and result['evidence_ids']==['ATT-1']
    assert service.learn_action_outcome(action_id='ACT-1')['id']==result['id']
    assert len(store.outcomes)==1


def test_reactive_replan_resume_keeps_unaffected_completed_work(monkeypatch):
    # A completed checkpoint is resumable only after a confirmed event flagged impacted tasks.
    from backend.tests.test_agent_memory_component3 import Backend
    backend=Backend()
    cp=checkpoint()
    cp.update(status='REPLAN_REQUIRED', reactive_affected_tasks=['check_source','verify'])
    backend.checkpoint(cp['id'],owner='tester',payload=cp,revision=cp['revision'])
    runtime=Supervisor(provider=ScriptedProvider(),tools=ToolRegistry(graph),store=Store(),
                       tenant='asteria',permissions=PERMS,
                       memory=AgentMemory(backend=backend,snapshot_factory=graph,tenant='asteria'))
    # Synthetic checkpoint's task names are not aligned to scripted incident tool calls,
    # but pre-existing unrelated completed work must remain completed.
    response=runtime.run(SupervisorSettings(goal='Resume previously authorized source checking',allow_external_model=True),
                         subject='tester',resume_id=cp['id'])
    unchanged=next(t for t in response.tasks if t['id']=='unrelated')
    assert unchanged['attempts']==1 and unchanged['status']=='COMPLETED'
    assert any(e['kind']=='RESUMED' for e in response.events)
    assert backend.load_checkpoint(cp['id'],owner='tester')['revision']>cp['revision']
