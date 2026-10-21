"""Component 6 acceptance: truthful replay, secure controls, cooperative pause/restart."""
import json
import threading

import pytest
from fastapi.testclient import TestClient

from backend.app.agent_runtime.workspace import (WorkspaceStart, WorkspaceRunner, format_workspace,
    build_replay, task_comparison)
from backend.app.agent_runtime.supervisor import Supervisor, SupervisorSettings
from backend.app.agent_runtime.memory import AgentMemory
from backend.app.agent_runtime.tools import ToolRegistry
from backend.tests.test_supervisor_component2 import graph, ScriptedProvider, Store, INCIDENT
from backend.tests.test_agent_memory_component3 import Backend
from backend.app.main import app

PERMS=frozenset({'READ_GRAPH','READ_EVIDENCE','CREATE_INVESTIGATION'})


def test_no_consent_is_never_assumed():
    request=WorkspaceStart(goal='Investigate incident and validate graph evidence')
    assert request.settings().allow_external_model is False
    assert request.max_parallel == 3
    with pytest.raises(Exception):
        WorkspaceStart(goal='Do it')


def test_workspace_status_reports_worker_interruption_not_fake_running():
    entry={'id':'SRUN-'+'A'*32,'goal':'Investigate graph evidence','status':'RUNNING',
           'allow_external_model':True}
    assert format_workspace(entry,is_live=False)['status']=='INTERRUPTED'
    assert format_workspace(entry,is_live=True)['status']=='RUNNING'
    assert format_workspace({**entry,'status':'PAUSED'},is_live=False)['recovery_available']


def test_replay_contains_only_persisted_events_and_checkpoint_metadata():
    run={'tasks':[{'id':'a','status':'COMPLETED'}],
         'events':[{'index':2,'kind':'TASK_COMPLETED','summary':'validated','created_at':'z'},
                   {'index':1,'kind':'ASSIGN','summary':'assigned','created_at':'a'}]}
    replay=build_replay(run,{'revision':5,'status':'COMPLETED'})
    assert [e['kind'] for e in replay['events']]==['ASSIGN','TASK_COMPLETED']
    assert replay['checkpoints']['revision']==5
    assert 'reasoning' in replay['limitations']
    changes=task_comparison({'tasks':[{'id':'a','status':'RUNNING'}]},run)
    assert changes[0]['checkpoint_status']=='RUNNING'
    assert changes[0]['current_status']=='COMPLETED'


def test_workspace_runner_blocks_duplicate_active_worker():
    worker=WorkspaceRunner()
    waiting=threading.Event()
    started=threading.Event()
    worker.submit(tenant='asteria',run_id='SRUN-1',execute=lambda:(started.set(),waiting.wait(timeout=2)))
    assert started.wait(1)
    with pytest.raises(ValueError, match='active worker'):
        worker.submit(tenant='asteria',run_id='SRUN-1',execute=lambda:None)
    waiting.set()
    worker.futures[('asteria','SRUN-1')].result(timeout=2)


def test_supervisor_pauses_at_safe_boundary_and_resumes_checkpoint():
    provider=ScriptedProvider()
    backend=Backend()
    memory=AgentMemory(backend=backend,snapshot_factory=graph,tenant='asteria')
    store=Store()
    sup=Supervisor(provider=provider,tools=ToolRegistry(graph),store=store,
                   tenant='asteria',permissions=PERMS,memory=memory)
    settings=SupervisorSettings(goal='Investigate route outage and verify dependencies',
                                source_entity_id=INCIDENT,allow_external_model=True)
    report=sup.run(settings,subject='operator',run_id='SRUN-'+'A'*32,control_check=lambda:'PAUSE')
    assert report.status=='PAUSED'
    assert all(t['status']=='PENDING' for t in report.tasks)
    assert not provider.calls
    cp=backend.load_checkpoint(report.id,owner='operator')
    assert cp['status']=='PAUSED'
    resumed=sup.run(settings,subject='operator',resume_id=report.id,control_check=lambda:'')
    assert resumed.status=='COMPLETED',resumed.error
    assert all(t['status']=='COMPLETED' for t in resumed.tasks)
    assert sum(provider.calls.values())==8  # two bounded model turns per specialist
    assert any(e['kind']=='RESUMED' for e in resumed.events)


def test_supervisor_cancel_does_not_dispatch_business_action_or_specialist():
    sup=Supervisor(provider=ScriptedProvider(),tools=ToolRegistry(graph),store=Store(),
                   tenant='asteria',permissions=PERMS)
    settings=SupervisorSettings(goal='Investigate route outage and verify dependencies',
                                source_entity_id=INCIDENT,allow_external_model=True)
    result=sup.run(settings,subject='operator',control_check=lambda:'CANCEL')
    assert result.status=='CANCELLED'
    assert all(t['status']=='PENDING' for t in result.tasks)
    assert result.answer==''


def test_unauthenticated_workspace_and_nonconsensual_launch_rejected():
    client=TestClient(app)
    assert client.get('/api/v1/agent-runtime/workspace/capabilities').status_code==401
    headers={'Authorization':'Bearer test-asteria-admin-token','X-Tenant-ID':'asteria'}
    r=client.post('/api/v1/agent-runtime/workspace/runs',headers=headers,
       json={'goal':'Investigate route outage and verify dependencies','allow_external_model':False})
    assert r.status_code==422
    assert r.json()['error']['code']=='CONSENT_REQUIRED'
    reader={'Authorization':'Bearer test-reader-token','X-Tenant-ID':'northstar'}
    r=client.post('/api/v1/agent-runtime/workspace/runs',headers=reader,
       json={'goal':'Investigate route outage and verify dependencies','allow_external_model':True})
    assert r.status_code==403
    r=client.get('/api/v1/agent-runtime/workspace/runs/not-a-run',headers=headers)
    assert r.status_code==422


def test_sensitive_workspace_controls_require_role_and_model_consent():
    client=TestClient(app)
    reader={'Authorization':'Bearer test-reader-token','X-Tenant-ID':'northstar'}
    r=client.post('/api/v1/agent-runtime/workspace/runs/SRUN-'+'A'*32+'/control',headers=reader,
         json={'operation':'cancel'})
    assert r.status_code==403


def test_pause_after_completed_task_preserves_progress_on_resume():
    provider=ScriptedProvider()
    backend=Backend()
    memory=AgentMemory(backend=backend,snapshot_factory=graph,tenant='asteria')
    store=Store()
    sup=Supervisor(provider=provider,tools=ToolRegistry(graph),store=store,
                   tenant='asteria',permissions=PERMS,memory=memory)
    settings=SupervisorSettings(goal='Investigate route outage and verify dependencies',
                                source_entity_id=INCIDENT,allow_external_model=True,max_parallel=1)
    paused=sup.run(settings,subject='operator',run_id='SRUN-'+'B'*32,
            control_check=lambda: 'PAUSE' if any(e['kind']=='TASK_COMPLETED' for e in store.events) else '')
    assert paused.status=='PAUSED'
    completed={t['id'] for t in paused.tasks if t['status']=='COMPLETED'}
    assert len(completed)==1
    old_calls=dict(provider.calls)
    resumed=sup.run(settings,subject='operator',resume_id=paused.id,control_check=lambda:'')
    assert resumed.status=='COMPLETED',resumed.error
    assert all(provider.calls[k]==old_calls[k] for k in completed)
    assert all(t['status']=='COMPLETED' for t in resumed.tasks)


def test_retry_only_failed_and_dependent_tasks_with_fresh_consent():
    provider=ScriptedProvider(bad_citation=True)
    backend=Backend()
    memory=AgentMemory(backend=backend,snapshot_factory=graph,tenant='asteria')
    store=Store()
    sup=Supervisor(provider=provider,tools=ToolRegistry(graph),store=store,
                   tenant='asteria',permissions=PERMS,memory=memory)
    settings=SupervisorSettings(goal='Investigate route outage and verify dependencies',
                                source_entity_id=INCIDENT,allow_external_model=True)
    initial=sup.run(settings,subject='operator',run_id='SRUN-'+'C'*32)
    assert initial.status=='NEEDS_REVIEW'
    assert next(t for t in initial.tasks if t['id']=='analyze_dependencies')['status']=='COMPLETED'
    healthy=ScriptedProvider()
    sup.provider=healthy
    retry=sup.run(settings,subject='operator',resume_id=initial.id,retry_failed=True)
    assert retry.status=='COMPLETED',retry.error
    assert not healthy.calls.get('analyze_dependencies')
    assert all(t['status']=='COMPLETED' for t in retry.tasks)
