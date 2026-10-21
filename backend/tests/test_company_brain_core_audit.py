"""Offline verification of the four submitted VERINEX Company Brain components.
Execute from the repository root: python -m pytest -q backend/tests/test_company_brain_core_audit.py
Uses real uploaded source bodies and lightweight fakes for external services;
not a substitute for live FalkorDB, providers, or pglast integration.
"""
from __future__ import annotations
import ast, copy, json, os, sys
from pathlib import Path
from types import SimpleNamespace, ModuleType
from unittest.mock import Mock
import pytest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.ingestion.models import SourceConfig, SourceRecordEnvelope, AdapterPage, NormalizedRecord, ResolutionDecision, ResolutionStatus, ProposedMutation, IngestionRunStatus
from backend.app.ingestion.normalization.mappings import normalizer_for, NORMALIZERS
from backend.app.ingestion.adapters.base import checksum_payload
from backend.app.services.phase6_utils import now_iso, stable_id

def module_extract(filename, names, globals_dict=None):
    body=ast.parse(Path(filename).read_text(encoding='utf-8'))
    selected=[]
    for n in body.body:
        if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in names:
            selected.append(n)
        elif isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id in names for t in n.targets):
            selected.append(n)
        elif isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name) and n.target.id in names:
            selected.append(n)
    sys.modules.setdefault('__audit__', ModuleType('__audit__'))
    ctx={'__name__':'__audit__','Any':object,'SourceConfig':SourceConfig,'now_iso':now_iso,'stable_id':stable_id,'json':json,'os':os}
    ctx.update(globals_dict or {})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+selected,type_ignores=[])),str(filename),'exec'),ctx)
    return ctx

# Only these three uploaded source files are extracted. The real normalizers use the uploaded normalization.zip overlay.
SRC=ROOT / 'backend/app/ingestion/source_control.py'; REG=ROOT / 'backend/app/ingestion/registry.py'; PIPE=ROOT / 'backend/app/ingestion/pipeline.py'

class FakeCreds:
    provider='memory'
    def __init__(self): self.calls=[]
    def put(self,*args): self.calls.append(args); return 'secret://test'
    def exists(self,ref): return True
    def metadata(self,ref): return {'configured':True}

class FakeGraph:
    settings=SimpleNamespace(tenant_id='eval')
    def query(self,query,params=None): return None
    def health_check(self): return {'ok':True}

class FakeSnap:
    @staticmethod
    def load(client): return SimpleNamespace(node=lambda x: None, nodes={}, edges=[], edges_from=lambda *_:[], edges_to=lambda *_:[])

def source_env():
    from dataclasses import dataclass
    from datetime import datetime,timezone
    from pathlib import Path
    from urllib.parse import urlparse
    import ast as pyast
    writes=[]
    def record_node(client,label,id,props): writes.append((label,id,props))
    from backend.app.ingestion.models import TrustClass
    ctx=module_extract(SRC, {'ConnectorDefinition','CONNECTORS','MAPPING_EXAMPLES','_parse_jsonish','SourceControlService'}, {
        'dataclass':dataclass,'datetime':datetime,'timezone':timezone,'Path':Path,'urlparse':urlparse,'ast':pyast,
        'TrustClass':TrustClass,'GraphSnapshot':FakeSnap,'upsert_node':record_node,
        'parse_repository':lambda s: s.split('/'),
    })
    svc=object.__new__(ctx['SourceControlService'])
    svc.client=FakeGraph(); svc.credentials=FakeCreds(); svc.events=SimpleNamespace(record=lambda *a,**kw:None)
    return ctx, svc, writes

def test_source_config_rejects_unregistered_live_api():
    _,svc,_=source_env()
    with pytest.raises(ValueError,match='server-registered'):
        svc._safe_connection_config('internal_api','live',{'registered_endpoint':'arbitrary'})

def test_source_catalog_exposes_eight_connector_types():
    ctx,svc,writes=source_env()
    assert set(ctx['CONNECTORS'])=={'github','jira','slack','teams','database','internal_api','documents','telemetry'}
    assert len(svc.list_connectors())==8

def test_source_rejects_top_level_token():
    _,svc,_=source_env()
    with pytest.raises(ValueError):
        svc._safe_connection_config('github','live',{'token':'plaintext-secret','base_url':'https://api.github.com'})

def test_source_credentials_not_written_before_invalid_mode():
    _,svc,_=source_env()
    with pytest.raises(ValueError,match='connection_mode'):
        svc.create_source({'connector_type':'github','display_name':'Bad mode','connection_mode':'invalid','credentials':{'token':'sensitive'}},actor_id='u')
    assert svc.credentials.calls == []

def test_source_credentials_not_written_before_unsupported_live_mode():
    _,svc,_=source_env()
    with pytest.raises(ValueError,match='not implemented'):
        svc.create_source({'connector_type':'teams','display_name':'No live','connection_mode':'live','credentials':{'token':'sensitive'}},actor_id='u')
    assert svc.credentials.calls == []

def registry_env():
    writes=[]
    def write(client,label,id,props): writes.append((label,id,props))
    class GoodAdapter:
        def __init__(self, config): self.config=config
    class BrokenAdapter:
        def __init__(self, config): raise RuntimeError('constructor failed')
    ctx=module_extract(REG,{'SourceRegistry'}, {'ADAPTERS':{'github':GoodAdapter,'slack':BrokenAdapter}, 'upsert_node':write,'TrustClass':__import__('backend.app.ingestion.models',fromlist=['TrustClass']).TrustClass})
    return ctx['SourceRegistry'], writes, GoodAdapter

def cfg(kind='github'):
    return SourceConfig(id='S1',source_type=kind,name='test',source_instance='test')

def test_registry_initializes_and_selects_adapter():
    Registry, writes, Adapter=registry_env(); r=Registry(FakeGraph()); c=cfg()
    r.register(c,persist=False)
    assert r.get('S1')[0] is c and isinstance(r.get('S1')[1],Adapter)

def test_registry_rejects_unsupported_type():
    Registry,_,_=registry_env(); r=Registry()
    with pytest.raises(ValueError,match='Unsupported source type'):r.register(cfg('unknown'),persist=False)

def test_registry_does_not_half_register_when_constructor_fails():
    Registry,_,_=registry_env(); r=Registry()
    with pytest.raises(RuntimeError,match='constructor failed'):r.register(cfg('slack'),persist=False)
    assert r.configs() == []

def test_registry_does_not_reset_created_at_on_persist():
    Registry,writes,_=registry_env(); graph=FakeGraph(); graph.query=Mock()
    r=Registry(graph); c=cfg()
    r.persist_source(c);r.persist_source(c)
    assert 'created_at' not in writes[-1][2], 'upsert_node overwrites created_at on every sync'
    assert graph.query.call_count==2
    assert 'coalesce(n.created_at' in graph.query.call_args.args[0]

def test_pipeline_rejects_unknown_mode():
    ctx=module_extract(PIPE, {'IngestionPipeline'}, {'IngestionRunStatus':IngestionRunStatus,'normalizer_for':lambda c: None,'IngestionReport':__import__('backend.app.ingestion.models',fromlist=['IngestionReport']).IngestionReport})
    obj=object.__new__(ctx['IngestionPipeline']); obj.registry=SimpleNamespace(get=lambda id:(cfg(),None));obj.client=FakeGraph()
    with pytest.raises(ValueError,match='mode'):
        obj.sync('S1',mode='bogus',dry_run=True)

def test_pipeline_rejects_bad_bounds():
    ctx=module_extract(PIPE, {'IngestionPipeline'}, {'IngestionRunStatus':IngestionRunStatus})
    obj=object.__new__(ctx['IngestionPipeline'])
    with pytest.raises(ValueError,match='max_records'):obj.sync('S1',max_records=0)
    with pytest.raises(ValueError,match='batch_size'):obj.sync('S1',batch_size=501)

@pytest.mark.parametrize('kind,record_type,raw,expected',[
 ('github','repository',{'name':'svc','full_name':'co/svc'},'System'),
 ('jira','issue',{'key':'OPS-8','summary':'Investigate timeout'},'Task'),
 ('slack','message',{'user_id':'U1','text':'Deployment observed'},'Document'),
 ('teams','message',{'user_id':'U1','text':'Deployment observed'},'Document'),
 ('documents','policy_document',{'title':'Policy X','policy':{'policy_id':'X','name':'Policy X'}},'Policy'),
 ('telemetry','alert',{'system':'inventory','name':'Outage'},'Event'),
 ('database','service_record',{'system':'billing','depends_on':'postgres'},'System'),
 ('internal_api','service_record',{'system':'billing','owner_team':'platform'},'Team'),
])
def test_normalizers_produce_expected_canonical_types(kind,record_type,raw,expected):
    config=SourceConfig(id='S1',source_type=kind,name='test',source_instance='inst')
    rec=SourceRecordEnvelope(source_type=kind,source_instance='inst',external_id='x1',record_type=record_type,fetched_at=now_iso(),raw_metadata=raw,checksum=checksum_payload(raw))
    out=normalizer_for(config).normalize('R1',rec)
    assert isinstance(out,NormalizedRecord)
    assert any(e.ontology_type==expected for e in out.entities), (kind,record_type,out.entities)
    assert all(rel.source_key in {e.key for e in out.entities} and rel.target_key in {e.key for e in out.entities} for rel in out.relations)

def test_normalization_mapping_coverage_matches_registry_catalog():
    assert len(NORMALIZERS)==8

def test_normalizer_rejects_unsupported_schema_version():
    c=cfg();rec=SourceRecordEnvelope(source_type='github',source_instance='x',external_id='e',record_type='repository',fetched_at=now_iso(),checksum='abc',schema_version='99')
    with pytest.raises(ValueError,match='Unsupported'):
        normalizer_for(c).normalize('x',rec)

def test_normalizer_sql_path_requires_validated_metadata():
    c=cfg();rec=SourceRecordEnvelope(source_type='github',source_instance='x',external_id='e',record_type='sql_file',fetched_at=now_iso(),checksum='abc')
    with pytest.raises((ValueError,ImportError,ModuleNotFoundError)):
        normalizer_for(c).normalize('x',rec)


@pytest.mark.parametrize('kind', ['slack','teams'])
def test_message_has_authorship_link(kind):
    c=cfg(kind)
    raw={'user_id':'U123','text':'Deployment notice'}
    rec=SourceRecordEnvelope(source_type=kind,source_instance='test',external_id='M1',record_type='message',fetched_at=now_iso(),raw_metadata=raw,checksum=checksum_payload(raw))
    out=normalizer_for(c).normalize('SR1',rec)
    assert any(r.source_key=='author' and r.rel_type=='PRODUCED' and r.target_key=='message' for r in out.relations)

@pytest.mark.parametrize('kind,record_type,raw', [
 ('teams','message',{'user_id':'U123','text':'hello'}),
 ('internal_api','service_record',{'system':'api','depends_on':'db'}),
])
def test_delegated_normalizers_keep_source_mapping_identity(kind,record_type,raw):
    rec=SourceRecordEnvelope(source_type=kind,source_instance='test',external_id='1',record_type=record_type,fetched_at=now_iso(),raw_metadata=raw,checksum=checksum_payload(raw))
    out=normalizer_for(cfg(kind)).normalize('SR1',rec)
    assert out.mapping_rule.startswith(kind+':')


def test_source_live_configuration_does_not_fake_authentication_pass():
    ctx,svc,writes=source_env()
    svc._source_node=lambda source_id:{'id':source_id}
    svc._registry=lambda source_id:SimpleNamespace(get=lambda sid:(cfg(),SimpleNamespace(health_check=lambda:{'ok':True,'live':True,'configured':True})))
    r=svc.test_connection('S1',actor_id='tester')
    assert r['status']=='UNVERIFIED'
    assert r['checks']['authentication']=='UNKNOWN'
    assert r['checks']['required_permission']=='UNKNOWN'
    assert any(n=='DataSource' and props.get('connection_status')=='UNVERIFIED' for n,_,props in writes)

def test_source_live_with_verified_probe_can_pass():
    ctx,svc,writes=source_env()
    svc._source_node=lambda source_id:{'id':source_id}
    health={'ok':True,'live':True,'verified_live':True}
    svc._registry=lambda source_id:SimpleNamespace(get=lambda sid:(cfg(),SimpleNamespace(health_check=lambda:health)))
    r=svc.test_connection('S1',actor_id='tester')
    assert r['status']=='HEALTHY'

def test_source_sync_setup_failure_resets_running_state():
    ctx,svc,writes=source_env()
    svc._source_node=lambda source_id:{'id':source_id}
    svc._pipeline=lambda source_id:(_ for _ in ()).throw(RuntimeError('mock setup failure'))
    with pytest.raises(RuntimeError,match='mock setup failure'):
        svc.sync('S1',actor_id='tester')
    assert any(n=='DataSource' and props.get('last_ingestion_status')=='FAILED' for n,_,props in writes)

def pipeline_env():
    from backend.app.ingestion.models import IngestionReport,TrustClass
    writes=[]
    def write(client,label,node_id,props):writes.append((label,node_id,props))
    ctx=module_extract(PIPE, {'IngestionPipeline'}, {
        'GraphSnapshot':FakeSnap,'upsert_node':write,'IngestionRunStatus':IngestionRunStatus,'IngestionReport':IngestionReport,
        'normalizer_for':normalizer_for,'ProposedMutation':ProposedMutation,
        'graph_delta':lambda before,after,ids:{},
    })
    return ctx['IngestionPipeline'],writes

def make_pipeline(dry_run):
    Pipeline,writes=pipeline_env()
    obj=object.__new__(Pipeline)
    obj.client=FakeGraph()
    from backend.app.ingestion.models import TrustClass
    config=cfg('database').model_copy(update={'trust_class':TrustClass.AUTHORITATIVE})
    raw={'system':'billing','depends_on':'postgres'}
    rec=SourceRecordEnvelope(source_type='database',source_instance='test',external_id='r1',record_type='service_record',fetched_at=now_iso(),raw_metadata=raw,checksum=checksum_payload(raw),cursor='r1')
    adapter=SimpleNamespace(fetch=lambda **kw:AdapterPage(records=[rec],has_more=False,next_cursor='r1'),fetch_incremental=lambda **kw:AdapterPage(records=[rec],has_more=False,next_cursor='r1'))
    obj.registry=SimpleNamespace(get=lambda sid:(config,adapter),persist_source=Mock())
    obj.provenance=SimpleNamespace(source_record_id=lambda *a,**kw:'RECORD-1',create_run=lambda *a,**kw:'RUN-1',complete_run=Mock(),persist_source_record=lambda *a,**kw:('RECORD-1',False),link_resolution=Mock(),external_identity=Mock())
    obj.resolution=SimpleNamespace(preview=lambda entity,config:ResolutionDecision(entity_key=entity.key,status=ResolutionStatus.CREATED,canonical_id='ID-'+entity.key,confidence=1.0),resolve=lambda source_record_id,entity,config:ResolutionDecision(entity_key=entity.key,status=ResolutionStatus.CREATED,canonical_id='ID-'+entity.key,confidence=1.0))
    obj.writer=SimpleNamespace(write=lambda **kwargs:{'written_nodes':2,'written_relationships':1,'entity_map':{'system':'ID-system','dependency':'ID-dependency'},'warnings':[]})
    obj.artifacts=SimpleNamespace(should_externalize=lambda payload:False)
    obj.events=SimpleNamespace(record=Mock())
    obj.retrieval_indexer=None
    obj._reactive=None
    return obj,writes

def test_pipeline_read_only_dry_run_proposes_entities_and_relations():
    obj,writes=make_pipeline(True)
    result=obj.sync('S1',mode='full',max_records=1,batch_size=1,dry_run=True)
    assert result.status==IngestionRunStatus.DRY_RUN
    assert result.fetched==1 and result.normalized==1 and result.resolved==2
    assert len([m for m in result.proposed_mutations if m.kind=='node'])==2
    assert len([m for m in result.proposed_mutations if m.kind=='relationship'])==1
    assert writes==[]

def test_pipeline_persists_resolved_record_and_cursor():
    obj,writes=make_pipeline(False)
    result=obj.sync('S1',mode='full',max_records=1,batch_size=1,dry_run=False)
    assert result.status==IngestionRunStatus.SUCCEEDED
    assert result.fetched==1 and result.normalized==1 and result.resolved==2 and result.written==1
    assert any(n=='DataSource' and props.get('last_successful_cursor')=='r1' for n,_,props in writes)
    obj.provenance.complete_run.assert_called_once()
    obj.events.record.assert_called()


def test_source_rejects_secret_embedded_in_url():
    _,svc,_=source_env()
    with pytest.raises(ValueError,match='base_url'):
        svc._safe_connection_config('github','live',{'base_url':'https://my-user:secret@api.github.com'})


def page_cursor_pipeline():
    obj,writes=make_pipeline(False)
    def rec(n):
        raw={'system':f'service{n}','depends_on':'postgres'}
        return SourceRecordEnvelope(source_type='database',source_instance='test',external_id=f'r{n}',record_type='service_record',fetched_at=now_iso(),raw_metadata=raw,checksum=checksum_payload(raw),cursor='PAGE2')
    page=AdapterPage(records=[rec(1),rec(2)],next_cursor='PAGE2',has_more=True)
    config,_=obj.registry.get('S1')
    obj.registry=SimpleNamespace(get=lambda sid:(config,SimpleNamespace(fetch=lambda **kw:page,fetch_incremental=lambda **kw:page)),persist_source=Mock())
    return obj,writes

def test_pipeline_crash_mid_page_does_not_skip_unprocessed_records():
    obj,writes=page_cursor_pipeline()
    out=obj.sync('S1',mode='full',batch_size=2,max_records=2,fail_after_committed=1)
    assert out.status==IngestionRunStatus.PARTIAL
    assert not any(props.get('last_successful_cursor')=='PAGE2' for _,_,props in writes)

def test_pipeline_commits_shared_page_cursor_only_after_all_records():
    obj,writes=page_cursor_pipeline()
    out=obj.sync('S1',mode='full',batch_size=2,max_records=2)
    assert out.status==IngestionRunStatus.SUCCEEDED and out.written==2
    updates=[props.get('last_successful_cursor') for _,_,props in writes if 'last_successful_cursor' in props]
    assert updates==['PAGE2']
