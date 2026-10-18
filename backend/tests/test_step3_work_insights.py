from backend.app.services.phase4_graph import GraphSnapshot,GraphEdge
from backend.app.services.work_insights_service import task_dependency_analysis,task_insights,agent_memory


def snapshot(nodes,edges):
    return GraphSnapshot({n['id']:n for n in nodes},[GraphEdge(a,r,b,props) for a,r,b,*other in edges for props in [other[0] if other else {}]])


def sample_graph():
    ns=[
        {'id':'PLAN-1','_labels':['Entity','Plan']},
        {'id':'TASK-A','_labels':['Entity','Task'],'name':'Investigate','status':'COMPLETED'},
        {'id':'TASK-B','_labels':['Entity','Task'],'status':'OPEN','expected_output_type':'REPORT'},
        {'id':'TASK-C','_labels':['Entity','Task'],'status':'BLOCKED'},
        {'id':'AGENT-1','_labels':['Entity','Agent']},
        {'id':'EXEC-1','_labels':['Entity','Execution'],'task_id':'TASK-B','status':'PAUSED','attempt':2},
        {'id':'CHK-1','_labels':['Entity','Checkpoint'],'task_id':'TASK-B','agent_id':'AGENT-1','scope':'TASK','state_summary':'Task paused','created_at':'2026-10-10'},
        {'id':'FIND-1','_labels':['Entity','Finding'],'scope':'SHARED','statement':'Finding A'},
        {'id':'FIND-PRIVATE','_labels':['Entity','Finding'],'scope':'BRANCH','statement':'Private'},
        {'id':'E-1','_labels':['Entity','Evidence']},
        {'id':'EVT-1','_labels':['Entity','Event'],'event_type':'EXECUTION_PAUSED','occurred_at':'2026-10-10'},
    ]
    es=[('PLAN-1','PLAN_HAS_TASK',i) for i in ('TASK-A','TASK-B','TASK-C')]+[
        ('TASK-B','REQUIRES','TASK-A'),('TASK-C','REQUIRES','TASK-A'),('TASK-C','REQUIRES','TASK-B'),
        ('TASK-B','CLAIMED_BY','AGENT-1'),('TASK-B','HAS_EXECUTION','EXEC-1'),('TASK-B','HAS_CHECKPOINT','CHK-1'),
        ('AGENT-1','PRODUCED','FIND-1'),('AGENT-1','PRODUCED','FIND-PRIVATE'),
        ('FIND-1','DERIVED_FROM','E-1'),('FIND-1','ABOUT','TASK-B'),('E-1','ABOUT','TASK-B'),
        ('EVT-1','ABOUT','TASK-B'),('EVT-1','ABOUT','EXEC-1'),
    ]
    return snapshot(ns,es)


def test_dependency_waves_and_longest_structural_chain():
    out=task_dependency_analysis(sample_graph(),'PLAN-1')
    assert out['parallel_waves']==[['TASK-A'],['TASK-B'],['TASK-C']]
    assert out['longest_dependency_chain']==['TASK-A','TASK-B','TASK-C']
    assert out['longest_dependency_chain_is_duration_critical_path'] is False
    assert out['complete']==1 and out['blocked_task_ids']==['TASK-C']  # B depends on A (complete)


def test_cycle_is_detected_without_false_critical_path():
    snap=sample_graph()
    snap.add_edge('TASK-A','REQUIRES','TASK-C')
    out=task_dependency_analysis(snap,'PLAN-1')
    assert out['cycle_detected']
    assert out['longest_dependency_chain']==[]
    assert set(out['cycle_members_or_dependents'])=={'TASK-A','TASK-B','TASK-C'}


def test_tenant_snapshot_graph_insights_contain_real_events_and_evidence():
    output=task_insights(sample_graph(),'TASK-B')
    assert output['owner']['id']=='AGENT-1'
    assert output['evidence'][0]['id']=='E-1'
    assert output['events'][0]['event_type']=='EXECUTION_PAUSED'
    assert output['comparison']['execution_attempts']==2
    assert output['findings'][0]['id']=='FIND-1'


def test_memory_excludes_branch_private_and_marks_provenance():
    out=agent_memory(sample_graph(),'AGENT-1')
    assert set(x['record']['id'] for x in out['records'])=={'FIND-1','CHK-1'}
    finding=next(x for x in out['records'] if x['record']['id']=='FIND-1')
    assert finding['source_evidence'][0]['id']=='E-1'
    assert 'PRODUCED' in finding['provenance']
    assert 'READ_GRAPH' in finding['accessible_to']


def test_unknown_plan_agent_task_fail_closed():
    s=sample_graph()
    assert task_dependency_analysis(s,'PLAN-MISSING') is None
    assert task_insights(s,'TASK-MISSING') is None
    assert agent_memory(s,'AGENT-MISSING') is None
