"""Deterministically generate Asteria Logistics Group v1 demonstration fixtures.

Fixture generation is offline; it never connects to FalkorDB. Golden answers remain
outside the seed payload, so the app/agents never receive evaluator-only truths.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / 'fixtures' / 'asteria' / 'v1'
TENANT = 'asteria'
DATE = '2025-01-01T00:00:00+05:30'

class Pack:
    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self.sources = {}
        self.scenarios = []
        self.truth = {}

    def n(self, ident, label, name, *, at=DATE, **props):
        if ident in self.nodes: raise ValueError(f'duplicate node: {ident}')
        base = {'id':ident, 'tenant_id':TENANT, 'name':name, 'created_at':at,
                'fixture_pack':'asteria-v1', 'synthetic':True, **props}
        self.nodes[ident] = {'id':ident,'label':label,'properties':base}
        return ident

    def e(self, source, kind, target, *, at=DATE, end=None, confidence=1.0, **props):
        key = (source,kind,target,at)
        if key in self.edges: raise ValueError(f'duplicate edge: {key}')
        d = {'edge_id':f'{source}|{kind}|{target}|{at}', 'valid_from':at,
             'confidence':confidence, **props}
        if end: d['valid_until'] = end
        self.edges[key] = {'source':source,'type':kind,'target':target,'properties':d}

    def scenario(self, key, track, title, summary, entry, focus, tests, *, visible=None, withheld=None):
        permitted = {
            'COMPANY_BRAIN': ['READ_GRAPH','READ_EVIDENCE'],
            'CONNECTED_AGENTS': ['READ_GRAPH','READ_EVIDENCE','CREATE_INVESTIGATION','CREATE_PLAN','PROPOSE_ACTION'],
            'AGENT_MEMORY_COORDINATION': ['READ_GRAPH','READ_EVIDENCE','CLAIM_TASK','WRITE_FINDING','CHECKPOINT'],
        }[track]
        self.scenarios.append({'scenario_id':key,'track':track,'title':title,
             'summary':summary,'entry_ids':entry,'focus_ids':focus,
             'starting_state':{'fixture_version':'asteria-v1','snapshot_as_of':'2026-10-12T12:45:00+05:30',
                 'entries':[{'id':ident,'current_status':self.nodes[ident]['properties'].get('status','N/A')}
                            for ident in entry]},
             'permitted_operations':permitted,
             'forbidden_operations':['BYPASS_POLICY_APPROVAL','EXPOSE_GOLD_ANSWERS','UNBOUNDED_DATABASE_MUTATION'],
             'test_prompts':tests,
             'visible_to_agents':visible or ['graph facts','source records','provenance'],
             'withheld_from_agents':withheld or ['golden answer','evaluator assertions']})

    def gold(self,key,paths,properties=None,absent=None, temporal=None, reason=''):
        self.truth[key]={'paths':paths, 'properties':properties or [],
                         'absent_relationships':absent or [],
                         'temporal':temporal or [], 'reason':reason,
                         'expected_outcome':'Identify the required connected relationships, retain source provenance, and report uncertainties rather than inventing conclusions.',
                         'success_criteria':{'required_paths':len(paths),
                                             'required_properties':len(properties or []),
                                             'absent_relationships':len(absent or []),
                                             'temporal_assertions':len(temporal or []),
                                             'pass_condition':'all asserted checks pass; no forbidden operations',
                                             'score_threshold':1.0}}

    def save(self):
        labels = Counter(n['label'] for n in self.nodes.values())
        # Referential integrity (even for cross-section references)
        missing=[(e['source'],e['type'],e['target']) for e in self.edges.values()
                 if e['source'] not in self.nodes or e['target'] not in self.nodes]
        if missing: raise ValueError(f'edges point to missing nodes: {missing[:20]}')
        for d in (PACK/'seed', PACK/'scenarios', PACK/'ground_truth'): d.mkdir(parents=True,exist_ok=True)
        # Separate files for navigability. The seeder loads each file in two passes.
        sections = {
          '01_organization': {'Team','Person','System','Project','DataSource','Tool','Policy','Document','Commitment'},
          '02_operations': {'Incident','Deployment','Change','Evidence','SourceRecord','Claim','Question','Event','Decision','Action','Investigation'},
          '03_coordination': {'Agent','Task','Plan','Execution','Checkpoint','WorkBranch','Handoff','Finding','Outcome','Lock','ActionAttempt','CompactionRecord'},
        }
        belonging={nid:next(sec for sec, labs in sections.items() if n['label'] in labs)
                   for nid,n in self.nodes.items()}
        for section in sections:
            nodes=sorted((n for nid,n in self.nodes.items() if belonging[nid]==section),key=lambda n:n['id'])
            edges=sorted((e for e in self.edges.values() if belonging[e['source']]==section and belonging[e['target']]==section),key=lambda e:(e['source'],e['type'],e['target'],e['properties']['valid_from']))
            payload={'scenario_id':f'ASTERIA-V1-{section.upper()}', 'title':f'Asteria demo {section}',
                     'description':'Synthetic, versioned organizational dataset; NOT a live connector.',
                     'tenant_id':TENANT,'nodes':nodes,'edges':edges}
            (PACK/'seed'/f'{section}.json').write_text(json.dumps(payload,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        # Cross-section edges separated so they can always be seeded after all nodes.
        cross=sorted((e for e in self.edges.values() if belonging[e['source']]!=belonging[e['target']]),key=lambda e:(e['source'],e['type'],e['target'],e['properties']['valid_from']))
        (PACK/'seed'/'04_cross_domain_edges.json').write_text(json.dumps({'scenario_id':'ASTERIA-V1-CROSS',
            'tenant_id':TENANT,'nodes':[],'edges':cross},indent=2)+'\n',encoding='utf-8')
        for item in self.scenarios:
            (PACK/'scenarios'/f"{item['scenario_id'].lower()}.json").write_text(json.dumps(item,indent=2)+'\n',encoding='utf-8')
        # One file contains all gold answers, intentionally not part of seeder.
        (PACK/'ground_truth'/'evaluation_only.json').write_text(json.dumps(self.truth,indent=2)+'\n',encoding='utf-8')
        manifest={'pack':'asteria','version':1,'organization':'Asteria Logistics Group',
           'tenant_id':TENANT,'graph':'asteria_company_brain_v1',
           'simulated_only':True,'default_legacy_graph':'company_brain',
           'created_for':'GraphHacks three-track reproducible demo',
           'seed_files':[f'seed/{x}.json' for x in sections]+['seed/04_cross_domain_edges.json'],
           'scenario_ids':[s['scenario_id'] for s in self.scenarios],
           'node_count':len(self.nodes),'relationship_count':len(self.edges),
           'node_types':dict(sorted(labels.items())),
           'ground_truth':'ground_truth/evaluation_only.json (evaluator only; never seed)',
           'fixture_revision':'v1-immutable',
           'data_sources':'All source records are synthetic and are NOT live connector data'}
        (PACK/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
        return manifest

p=Pack()
# The five operational domains intentionally share services, owners and change processes.
DEPARTMENTS=[('OPERATIONS','Fulfilment Operations'),('PLATFORM','Platform Engineering'),('DATA','Data & Applied Intelligence'),('FINANCE','Finance and Risk'),('COMMERCIAL','Commercial & Partner Experience'),('SECURITY','Trust, Security & Compliance'),('PEOPLE','People & Knowledge')]
TEAMS=[('WAREHOUSE','Warehouse Operations','OPERATIONS'),('DISPATCH','Dispatch Control','OPERATIONS'),('CARRIER','Carrier Integrations','OPERATIONS'),('NETWORK','Network Planning','OPERATIONS'),
 ('SRE','Reliability Engineering','PLATFORM'),('INTEGRATIONS','API and Integrations','PLATFORM'),('CORE','Core Services','PLATFORM'),('INFRA','Infrastructure & IAM','PLATFORM'),
 ('STREAM','Streaming Data','DATA'),('ANALYTICS','Business Analytics','DATA'),('ML','Forecasting and ML','DATA'),
 ('BILLING','Billing Operations','FINANCE'),('FRAUD','Revenue Assurance','FINANCE'),('TREASURY','Payments and Treasury','FINANCE'),
 ('SUPPORT','Customer Care','COMMERCIAL'),('PARTNERS','Enterprise Partnerships','COMMERCIAL'),('GROWTH','Demand & Growth','COMMERCIAL'),
 ('SECOPS','Security Operations','SECURITY'),('PRIVACY','Privacy and Data Governance','SECURITY'),('AUDIT','Internal Audit','SECURITY'),
 ('HR','People Operations','PEOPLE'),('ENABLE','Technical Enablement','PEOPLE'),('LEGACY','Legacy Integrations (retired)','PLATFORM')]
for dep, name in DEPARTMENTS:
 p.n('DEPT-'+dep,'Team',name,team_type='DEPARTMENT',status='ACTIVE')
for code,name,dep in TEAMS:
 p.n('TEAM-'+code,'Team',name,team_type='FUNCTION',status='RETIRED' if code=='LEGACY' else 'ACTIVE')
 p.e('TEAM-'+code,'PART_OF','DEPT-'+dep)

# Detailed ownership and expertise history (including departed and reorganized people).
NAMES=['Anaya Sethi','Rohan Gupta','Ishita Malhotra','Vikram Bedi','Meera Menon','Zoya Ali','Dev Khanna','Kavya Shah','Pranav Rao','Tara Kapoor','Ritwik Jain','Nisha Bose',
       'Arnav Iyer','Diya Kohli','Sameer Das','Pooja Nair','Shrey Arora','Ritika Bansal','Kabir Sood','Sana Dutta','Neel Chawla','Aditi Vyas','Farhan Sheikh','Palak Ghosh',
       'Mihir Chopra','Avni Mathur','Yash Verma','Mira Sachdeva','Naman Roy','Pari Gill','Arya Singhal','Tanvi Grover','Ojas Puri','Rhea Aggarwal','Siddharth K','Sakshi Mehta',
       'Anmol Taneja','Simran Bhat','Viraj Desai','Hina Suri','Sahil Prasad','Reva Sharma','Ahaan Joshi','Kiara Oberoi','Dhruv Gulati','Alina Paul','Vansh Nigam',
       'Sonia Malik','Aakash P','Devika Basu','Nikita Jain','Mohan Rao','Fiza Mir','Harini Sen','Parth Lal','Navya Singh','Priya V','Adarsh V','Juhi Goel','Shanaya Rao',
       'Samar Anand','Ritika Menon','Varun Shah','Ira Sinha','Aman Chopra','Zara Desai','Raghav Jain','Ayesha Seth','Nikhil Gupta']
FUNCTION_TEAMS=[x for x in TEAMS if x[0]!='LEGACY']
people_by_team={code:[] for code,_,_ in TEAMS}
for i,name in enumerate(NAMES):
 code=FUNCTION_TEAMS[i%len(FUNCTION_TEAMS)][0]
 pid=f'PERSON-AST-{i+1:03d}'
 p.n(pid,'Person',name,role=['Lead','Senior Engineer','Operations Specialist','Analyst','Coordinator'][i%5],
     employee_code=f'AST-{1001+i}',status='ACTIVE',joined_at=f'202{2+i%4}-05-01T00:00:00+05:30')
 p.e(pid,'MEMBER_OF','TEAM-'+code)
 people_by_team[code].append(pid)
 if i>=len(FUNCTION_TEAMS) and i%4==0:
  second=FUNCTION_TEAMS[(i+7)%len(FUNCTION_TEAMS)][0]
  if second!=code:p.e(pid,'COLLABORATES_WITH','TEAM-'+second)
# Expert ownership transitions and time-scoped historical people
retired_at='2026-07-01T00:00:00+05:30'
for code in ('SRE','CORE','CARRIER','PRIVACY'):
 idx=next(i for i,_ in enumerate(NAMES) if FUNCTION_TEAMS[i%len(FUNCTION_TEAMS)][0]==code)
 pid=f'PERSON-AST-{idx+1:03d}'
 p.nodes[pid]['properties'].update(status='LEFT',departure_at=retired_at)
 # Existing membership edge ended, no second membership created for LEFT actor.
 for v in p.edges.values():
  if v['source']==pid and v['type']=='MEMBER_OF':v['properties']['valid_until']=retired_at
p.n('PERSON-AST-LEGACY','Person','Elena Dsouza',role='Former Legacy Routing Architect',status='LEFT',departure_at='2026-06-15T00:00:00+05:30')
p.e('PERSON-AST-LEGACY','MEMBER_OF','TEAM-LEGACY',at='2024-03-01T00:00:00+05:30',end='2026-06-15T00:00:00+05:30')

SYSTEMS=[('ROUTE-API','Route Orchestration API','service','CORE'),('ROUTE-DB','Route State Database','database','CORE'),('DISPATCH','Dispatch Scheduler','service','DISPATCH'),('WMS','Warehouse Management','service','WAREHOUSE'),('PICK','Pick-Pack Orchestrator','service','WAREHOUSE'),('HANDHELD','Warehouse Handheld Client','client','WAREHOUSE'),
 ('CARRIER-GW','Carrier Gateway','service','CARRIER'),('CARRIER-CACHE','Carrier Rate Cache','cache','CARRIER'),('TRACK','Shipment Tracking','service','CARRIER'),('SLA','Delivery SLA Monitor','service','NETWORK'),('FLEET','Fleet Planning Engine','service','NETWORK'),('ETA','ETA Prediction Service','service','ML'),
 ('EVENT-BUS','Enterprise Event Bus','stream','STREAM'),('WAREHOUSE-DWH','Fulfilment Data Warehouse','database','ANALYTICS'),('LAKE','Data Lakehouse','database','STREAM'),('ANALYTICS','Operations BI','dashboard','ANALYTICS'),('FORECAST','Demand Forecasting','model','ML'),
 ('BILLING','Billing API','service','BILLING'),('LEDGER','Financial Ledger','database','TREASURY'),('PAYOUT','Carrier Payouts','service','TREASURY'),('FRAUD','Fraud Rules Engine','service','FRAUD'),('INVOICE','Invoice Reconciliation','service','BILLING'),
 ('PARTNER-PORTAL','Partner Portal','web','PARTNERS'),('PARTNER-API','Partner API','service','PARTNERS'),('CRM','Enterprise CRM','database','GROWTH'),('SUPPORT','Support Console','web','SUPPORT'),('NOTIFY','Customer Notifications','service','SUPPORT'),
 ('IAM','Identity Platform','service','INFRA'),('SECRETS','Secrets Vault','service','INFRA'),('AUDIT','Audit Event Store','database','AUDIT'),('DLP','Data Loss Prevention','service','PRIVACY'),('SIEM','Security Event Console','service','SECOPS'),
 ('POLICY','Policy Registry','service','PRIVACY'),('DOCSEARCH','Knowledge Search','service','ENABLE'),('STAFF','Staff Directory','service','HR'),('OLD-CARRIER','Retired Carrier Normalizer','service','LEGACY'),
 ('FALLBACK','Route Fallback Worker','worker','SRE'),('REGION-EDGE','Regional Routing Edge','service','INTEGRATIONS'),('CUST-ETL','Customer Export ETL','pipeline','STREAM'),('CONSENT','Partner Consent Service','service','PRIVACY')]
for code,name,kind,owner in SYSTEMS:
 pid='SYS-AST-'+code
 p.n(pid,'System',name,system_type=kind,status='ACTIVE' if code!='OLD-CARRIER' else 'ORPHANED',criticality='HIGH' if code in {'ROUTE-API','ROUTE-DB','EVENT-BUS','DISPATCH','CARRIER-GW','LEDGER'} else 'MEDIUM',business_domain=owner)
 if code!='OLD-CARRIER':p.e('TEAM-'+owner,'OWNS',pid)
 else:p.e('TEAM-LEGACY','OWNS',pid,at='2024-05-01T00:00:00+05:30',end='2026-07-01T00:00:00+05:30')
 p.e(people_by_team[owner][0] if owner!='LEGACY' else 'PERSON-AST-LEGACY','EXPERT_IN',pid,
     at='2024-07-01T00:00:00+05:30',end='2026-07-01T00:00:00+05:30' if owner=='LEGACY' else None)
# Directed from consumer to upstream dependency. Includes several shared bottlenecks.
DEPENDENCIES={'ROUTE-API':['ROUTE-DB','IAM','EVENT-BUS'],'DISPATCH':['ROUTE-API','FLEET','EVENT-BUS'],'WMS':['PICK','EVENT-BUS','IAM'],
 'PICK':['ROUTE-API','EVENT-BUS'],'HANDHELD':['WMS','IAM'],'CARRIER-GW':['CARRIER-CACHE','ROUTE-API','IAM'],
 'TRACK':['CARRIER-GW','EVENT-BUS'],'SLA':['TRACK','EVENT-BUS'],'FLEET':['ETA','ROUTE-API'],'ETA':['LAKE','EVENT-BUS'],
 'WAREHOUSE-DWH':['EVENT-BUS','LAKE'],'ANALYTICS':['WAREHOUSE-DWH'],'FORECAST':['WAREHOUSE-DWH','LAKE'],
 'BILLING':['TRACK','EVENT-BUS','LEDGER'],'PAYOUT':['BILLING','LEDGER'],'FRAUD':['LEDGER','EVENT-BUS'],
 'INVOICE':['PAYOUT','BILLING'],'PARTNER-PORTAL':['PARTNER-API','IAM'],'PARTNER-API':['TRACK','BILLING','IAM'],
 'SUPPORT':['CRM','TRACK','IAM'],'NOTIFY':['TRACK','EVENT-BUS'],'DLP':['LAKE','CONSENT'],'SIEM':['AUDIT','EVENT-BUS'],
 'POLICY':['AUDIT','IAM'],'DOCSEARCH':['STAFF','POLICY'],'OLD-CARRIER':['CARRIER-GW','EVENT-BUS'],'FALLBACK':['ROUTE-API','ROUTE-DB'],
 'REGION-EDGE':['ROUTE-API','CARRIER-GW'],'CUST-ETL':['LAKE','CONSENT'],'CONSENT':['POLICY','IAM']}
for s, targets in DEPENDENCIES.items():
 for target in targets:p.e('SYS-AST-'+s,'DEPENDS_ON','SYS-AST-'+target)
# Explicitly unregistered shadow dependency: no fabricated authoritative ownership.
p.e('SYS-AST-ANALYTICS','DEPENDS_ON','SYS-AST-LEDGER',at='2026-09-21T00:00:00+05:30',confidence=.43,discovery_method='audit-log',catalog_registered=False)
# Expert overlap anchored to actual incident investigations.
for i,(code,sys) in enumerate([('SRE','ROUTE-API'),('INTEGRATIONS','CARRIER-GW'),('PRIVACY','CUST-ETL'),('SECOPS','IAM'),('BILLING','LEDGER'),('NETWORK','ETA'),('WAREHOUSE','FALLBACK'),('CORE','WMS'),('AUDIT','BILLING')]):
 p.e(people_by_team[code][0],'EXPERT_IN','SYS-AST-'+sys,at='2025-09-01T00:00:00+05:30',confidence=.88,reason='cross-team incident expertise')

PROJECTS=[('ROUTE2','Route Engine v2 Transition','CORE'),('OMNI','Omnichannel Fulfilment','WAREHOUSE'),('CARRIER','Carrier Contract Consolidation','CARRIER'),('ETA','Arrival Time Accuracy','ML'),('PARTNER','Partner Self-Service','PARTNERS'),('LEDGER','Unified Carrier Ledger','TREASURY'),('BILL-DUP1','Automated Credit Notes','BILLING'),('BILL-DUP2','Self-Service Credit Notes','SUPPORT'),('CONSENT','Partner Privacy Controls','PRIVACY'),('SECZERO','Zero Trust Operations','SECOPS'),('RTOPS','Real-Time Operations Dashboard','ANALYTICS'),('REGION','Regional Routing Expansion','NETWORK'),('ARCHIVE','Legacy Adapter Retirement','INTEGRATIONS'),('KNOW','Knowledge Transfer 2026','ENABLE'),('OPS-AI','Incident Agent Assistant','SRE'),('FORECAST','Demand Forecast v3','ML')]
for code,name,team in PROJECTS:
 p.n('PROJ-AST-'+code,'Project',name,status='ACTIVE',owner_team='TEAM-'+team)
 p.e('TEAM-'+team,'RESPONSIBLE_FOR','PROJ-AST-'+code)
for a,b in [('OMNI','ROUTE2'),('REGION','ROUTE2'),('PARTNER','CARRIER'),('RTOPS','ETA'),('LEDGER','CARRIER'),('OPS-AI','KNOW'),('FORECAST','RTOPS'),('ARCHIVE','ROUTE2'),('CONSENT','PARTNER')]:
 p.e('PROJ-AST-'+a,'DEPENDS_ON','PROJ-AST-'+b)
for project,sys in [('ROUTE2','ROUTE-API'),('ROUTE2','ROUTE-DB'),('OMNI','WMS'),('CARRIER','CARRIER-GW'),('ETA','ETA'),('PARTNER','PARTNER-PORTAL'),('LEDGER','LEDGER'),('BILL-DUP1','BILLING'),('BILL-DUP2','BILLING'),('CONSENT','CONSENT'),('SECZERO','IAM'),('RTOPS','ANALYTICS'),('REGION','REGION-EDGE'),('ARCHIVE','OLD-CARRIER'),('KNOW','DOCSEARCH'),('OPS-AI','FALLBACK'),('FORECAST','FORECAST')]:
 p.e('PROJ-AST-'+project,'AFFECTS','SYS-AST-'+sys)

SOURCES=[('GITHUB','GitHub Mirror','git'),('JIRA','Jira Project Export','issue_tracker'),('SLACK','Slack Channel Archive','chat'),('LOG','Application Log Archive','logs'),('TRACE','Distributed Traces','trace'),('METRIC','Prometheus Snapshots','metrics'),('DB','Warehouse Snapshot','database'),('POLICY','Policy Registry Export','documents'),('HR','HR Roster Snapshot','human_resources'),('AUDIT','Security Audit Trail','audit'),('CRM','Partner CRM Export','crm'),('POSTMORTEM','Incident Wiki Export','documents')]
for code,name,kind in SOURCES:
 p.n('DS-AST-'+code,'DataSource',name,source_type=kind,connection_status='SYNTHETIC_FIXTURE',authoritative=False,
     provenance_note='Generated source fixture only; no live connector credentials or sync')
for code,name,src in [('CODE','Source Commit Search','GITHUB'),('TICKETS','Issue Lookup','JIRA'),('CHAT','Message Search','SLACK'),('LOGS','Log Explorer','LOG'),('TRACES','Trace Explorer','TRACE'),('METRICS','Metric Explorer','METRIC'),('OWNERSHIP','HR/Ownership Lookup','HR'),('POLICIES','Policy Lookup','POLICY'),('DB','Snapshot Reader','DB'),('SECURITY','Audit Reader','AUDIT')]:
 p.n('TOOL-AST-'+code,'Tool',name,tool_type='retrieval',risk_level='READ_ONLY',fixture_only=True)
 p.e('TOOL-AST-'+code,'QUERIES','DS-AST-'+src)

POLICIES=[('ROUTE','Routing Schema Compatibility','2026-03-01T00:00:00+05:30','ACTIVE'),('ROLLBACK','SEV-1 Rollback Approval','2026-01-01T00:00:00+05:30','ACTIVE'),('CARRIER','Carrier Contract Escalation','2026-02-01T00:00:00+05:30','ACTIVE'),('PRIVACY','Customer Export Data Minimization','2026-02-15T00:00:00+05:30','ACTIVE'),('FINANCE','Payout Reconciliation Approval','2026-04-01T00:00:00+05:30','ACTIVE'),('OLD-SLA','Legacy Carrier SLA Escalation','2024-02-01T00:00:00+05:30','SUPERSEDED'),('NEW-SLA','Regional Carrier SLA Escalation','2026-07-01T00:00:00+05:30','ACTIVE'),('ACCESS','Privileged Access & Review','2026-01-01T00:00:00+05:30','ACTIVE'),('AUDIT','Immutable Incident Evidence','2025-06-01T00:00:00+05:30','ACTIVE'),('MEMORY','Agent Memory Promotion Rules','2026-08-01T00:00:00+05:30','ACTIVE'),('ACTION','Agent Governed Actions','2026-08-01T00:00:00+05:30','ACTIVE'),('RETENTION','Customer Data Retention','2026-03-01T00:00:00+05:30','ACTIVE')]
for code,name,at,status in POLICIES:
 p.n('POL-AST-'+code,'Policy',name,version='1.0' if code!='OLD-SLA' else '0.7',status=status,valid_from=at,
     authoritative=True,owner_team='TEAM-'+('PRIVACY' if code in {'PRIVACY','RETENTION','MEMORY'} else 'AUDIT'),
     summary=f'{name}. Synthetic policy with review and provenance context.')
# Historical policy must end before the replacement took effect.
p.nodes['POL-AST-OLD-SLA']['properties']['valid_until']='2026-07-01T00:00:00+05:30'
p.e('POL-AST-NEW-SLA','SUPERSEDES','POL-AST-OLD-SLA',at='2026-07-01T00:00:00+05:30')
for code,system in [('ROUTE','ROUTE-DB'),('ROLLBACK','ROUTE-API'),('CARRIER','CARRIER-GW'),('PRIVACY','CUST-ETL'),('FINANCE','PAYOUT'),('OLD-SLA','OLD-CARRIER'),('NEW-SLA','CARRIER-GW'),('ACCESS','IAM'),('AUDIT','AUDIT'),('MEMORY','DOCSEARCH'),('ACTION','FALLBACK'),('RETENTION','LAKE')]:
 p.e('POL-AST-'+code,'GOVERNS','SYS-AST-'+system,at=next(row[2] for row in POLICIES if row[0]==code),
     end='2026-07-01T00:00:00+05:30' if code=='OLD-SLA' else None)

for i,(name,about) in enumerate([('Routing API runbook','ROUTE-API'),('Rollback approval checklist','ROUTE-DB'),('Carrier integration guide','CARRIER-GW'),('Warehouse peak readiness','WMS'),('Payout reconciliation manual','PAYOUT'),('Customer export retention guide','CUST-ETL'),('SRE on-call history','FALLBACK'),('Legacy carrier migration diary','OLD-CARRIER'),('Agent handoff specification','DOCSEARCH'),('Incident evidence policy guide','AUDIT'),('2026 ownership register','STAFF'),('Platform migration calendar','ROUTE-API'),('Inventory anomaly review','ANALYTICS'),('Carrier approval matrix','CARRIER-GW'),('Partner incident playbook','PARTNER-API'),('Knowledge transfer retrospective','OLD-CARRIER')],1):
 did=f'DOC-AST-{i:03d}'
 p.n(did,'Document',name,document_type='INTERNAL_GUIDE',status='PUBLISHED',text=f'{name}. Asteria Logistics Group internal reference; contains synthetic demo-only information.')
 p.e(did,'ABOUT','SYS-AST-'+about)
 p.e(did,'DERIVED_FROM','DS-AST-'+('POLICY' if i%3==0 else 'POSTMORTEM'))

# Incident timeline grounded in a shared cross-system storyline; 12 different situations.
INCIDENTS=[('ROUTE-OUTAGE','Route planning failures after schema deployment','SEV-1','OPEN','ROUTE-API','2026-10-12T09:15:00+05:30'),
 ('CARRIER-LAG','Carrier labels generated hours late','SEV-2','OPEN','CARRIER-GW','2026-10-12T09:42:00+05:30'),
 ('WAREHOUSE-QUEUE','Warehouse picking queues stall','SEV-2','OPEN','WMS','2026-10-12T09:47:00+05:30'),
 ('PAYOUT-DRIFT','Carrier payouts disagree with confirmed shipments','SEV-2','OPEN','PAYOUT','2026-10-12T10:05:00+05:30'),
 ('PARTNER-SLA','Partner SLA escalation routes to retired owner','SEV-3','OPEN','OLD-CARRIER','2026-10-12T10:18:00+05:30'),
 ('SECURITY-EXPORT','Unreviewed customer export reaches analytics','SEV-2','OPEN','CUST-ETL','2026-10-10T13:00:00+05:30'),
 ('FORECAST-BIAS','Demand forecast drifts after routing outage','SEV-3','OPEN','FORECAST','2026-10-12T11:00:00+05:30'),
 ('ACCESS-EXPIRED','Service key rotated without on-call access update','SEV-2','RESOLVED','IAM','2026-08-25T08:00:00+05:30'),
 ('OLD-MIGRATION','Historical route schema incompatibility','SEV-2','RESOLVED','ROUTE-DB','2026-05-11T06:00:00+05:30'),
 ('INVOICE-DUP','Duplicate carrier invoice reconciliation','SEV-2','OPEN','INVOICE','2026-10-09T15:00:00+05:30'),
 ('SLA-RECON','Regional SLA dashboard misstates deliveries','SEV-3','OPEN','SLA','2026-10-12T11:25:00+05:30'),
 ('AGENT-RETRY','Incident agent repeats failed action after retry','SEV-3','OPEN','FALLBACK','2026-10-12T11:30:00+05:30')]
for code,title,severity,status,system,at in INCIDENTS:
 inc='INC-AST-'+code
 p.n(inc,'Incident',title,at=at,title=title,status=status,severity=severity,occurred_at=at,
     description=f'{title}. Simulated Asteria operations incident, investigate using connected graph evidence.')
 p.e(inc,'AFFECTS','SYS-AST-'+system,at=at)
for a,b in [('CARRIER-LAG','ROUTE-OUTAGE'),('WAREHOUSE-QUEUE','ROUTE-OUTAGE'),('PAYOUT-DRIFT','CARRIER-LAG'),('PARTNER-SLA','CARRIER-LAG'),('FORECAST-BIAS','ROUTE-OUTAGE'),('SLA-RECON','CARRIER-LAG'),('AGENT-RETRY','ROUTE-OUTAGE')]:
 p.e('INC-AST-'+a,'DEPENDS_ON','INC-AST-'+b,at='2026-10-12T12:00:00+05:30',reason='operational storyline link; not causal proof')

# Change/deployment records: historical migration and current regression.
for code,name,sys,at in [('ROUTE-V3','Route Schema v3 Release','ROUTE-DB','2026-10-12T09:05:00+05:30'),('CARRIER-ADAPT','Carrier Event Translator v2','CARRIER-GW','2026-10-11T19:00:00+05:30'),('WMS-PEAK','Peak Capacity Optimizations','WMS','2026-10-10T12:00:00+05:30'),('FIN-INVOICE','Ledger Validation v5','LEDGER','2026-10-08T06:00:00+05:30'),('PRIVACY-PIPE','Customer Export Pipeline v4','CUST-ETL','2026-10-09T09:00:00+05:30'),('HIST-ROUTE','Historical Route Schema v2','ROUTE-DB','2026-05-10T18:00:00+05:30'),('AUTH-ROTATE','Service Credential Rotation','IAM','2026-08-25T07:45:00+05:30'),('ML-ETA','ETA Model Release v8','ETA','2026-10-10T10:00:00+05:30'),('PARTNER-CRM','CRM Export Refactor','CRM','2026-10-06T09:00:00+05:30')]:
 did='DPL-AST-'+code; chid='CHG-AST-'+code
 p.n(did,'Deployment',name,status='DEPLOYED',deployed_at=at)
 p.n(chid,'Change',name+' change',status='APPLIED',change_type='SCHEMA_MIGRATION' if code in {'ROUTE-V3','HIST-ROUTE'} else 'SOFTWARE_RELEASE')
 p.e(did,'CHANGED','SYS-AST-'+sys,at=at)
 p.e(did,'CONTAINS',chid,at=at)
 p.e(chid,'CHANGED','SYS-AST-'+sys,at=at)
p.e('DPL-AST-ROUTE-V3','BEFORE','INC-AST-ROUTE-OUTAGE',at='2026-10-12T09:05:00+05:30')
p.e('DPL-AST-HIST-ROUTE','BEFORE','INC-AST-OLD-MIGRATION',at='2026-05-10T18:00:00+05:30')

# Structured synthetic source records and evidence. Evidence for each incident has contradictory assertions.
record_counter=0
def record(name,source,text,incident,kind,at, *, supports=None, refutes=None, confidence=.9):
 global record_counter
 record_counter+=1
 sid=f'SRCREC-AST-{record_counter:04d}';eid=f'EVD-AST-{record_counter:04d}'
 p.n(sid,'SourceRecord',name,at=at,source_type=source,source_key=f'asteria-v1/{source.lower()}/{record_counter:04d}',
     source_entity_id=f'SYN-{source}-{record_counter:04d}',content=text,fixture_only=True,ingestion_status='SIMULATED',checksum=f'fixture-{record_counter:04d}')
 p.e(sid,'DERIVED_FROM','DS-AST-'+source,at=at)
 p.e(sid,'ABOUT','INC-AST-'+incident,at=at)
 p.n(eid,'Evidence',name,at=at,evidence_type=kind,observed_at=at,content=text,confidence=confidence,
     source_ref_id=sid,classification='SYNTHETIC',provenance_status='SIMULATED')
 p.e(eid,'DERIVED_FROM',sid,at=at)
 p.e(eid,'ABOUT','INC-AST-'+incident,at=at)
 for cid in supports or []:p.e(eid,'SUPPORTS','CLM-AST-'+cid,at=at,confidence=confidence)
 for cid in refutes or []:p.e(eid,'REFUTES','CLM-AST-'+cid,at=at,confidence=confidence)
 return eid

def claim(code,incident,text,asserted_by=None,confidence=.55):
 cid='CLM-AST-'+code
 p.n(cid,'Claim',text,at='2026-10-12T09:55:00+05:30',status='OPEN',statement=text,assertion_kind='human_or_agent_hypothesis',confidence=confidence)
 p.e(cid,'ABOUT','INC-AST-'+incident,at='2026-10-12T09:55:00+05:30')
 if asserted_by:p.e(cid,'ASSERTED_BY',asserted_by,at='2026-10-12T09:55:00+05:30')
 return cid
claim('ROUTE-CPU','ROUTE-OUTAGE','Routing database CPU saturation was the initial trigger.',people_by_team['SRE'][0],.49)
claim('ROUTE-SCHEMA','ROUTE-OUTAGE','Route schema v3 rejects regional edge clients still on v2.',people_by_team['CORE'][0],.61)
p.e('CLM-AST-ROUTE-CPU','CONTRADICTS','CLM-AST-ROUTE-SCHEMA')
claim('CARRIER-TIME','CARRIER-LAG','Carrier gateway retry queue is delaying labels.',people_by_team['CARRIER'][0])
claim('CARRIER-VENDOR','CARRIER-LAG','External carrier outage is the sole reason for label delay.',people_by_team['PARTNERS'][0],.35)
p.e('CLM-AST-CARRIER-TIME','CONTRADICTS','CLM-AST-CARRIER-VENDOR')
claim('PAYOUT-EVENT','PAYOUT-DRIFT','Late shipment confirmations create payout reconciliation drift.',people_by_team['TREASURY'][0])
claim('PAYOUT-FRAUD','PAYOUT-DRIFT','Payout drift is caused by fraudulent settlements.',people_by_team['FRAUD'][0],.35)
p.e('CLM-AST-PAYOUT-EVENT','CONTRADICTS','CLM-AST-PAYOUT-FRAUD')
claim('OWNER-RETIRED','PARTNER-SLA','Escalation used a retired team with no current ownership.',people_by_team['PARTNERS'][0])
claim('PRIVACY-EXEMPT','SECURITY-EXPORT','Batch exports are exempt from consent checks.',people_by_team['STREAM'][0],.42)
claim('PRIVACY-BLOCK','SECURITY-EXPORT','Consent approval is required for the customer export.',people_by_team['PRIVACY'][0],.65)
p.e('CLM-AST-PRIVACY-EXEMPT','CONTRADICTS','CLM-AST-PRIVACY-BLOCK')
for x,c in [('ROUTE','ROUTE-OUTAGE'),('WAREHOUSE','WAREHOUSE-QUEUE'),('FORECAST','FORECAST-BIAS'),('INVOICE','INVOICE-DUP'),('AGENT','AGENT-RETRY')]:
 claim(f'{x}-PENDING',c,f'Initial operational hypothesis for {c}: further evidence required.',confidence=.35)
# Multiple provenance modalities for route incident and secondary incidents.
record('Git commit 8f4c10 route_schema_v3','GITHUB','commit 8f4c10: removed nullable carrier_zone_code for v3; v2 edge clients still write NULL.', 'ROUTE-OUTAGE','git_commit','2026-10-12T09:07:00+05:30',supports=['ROUTE-SCHEMA'])
record('Jira AST-4821 compatibility task','JIRA','AST-4821: mixed v2/v3 edge compatibility checklist marked blocked before rollout.', 'ROUTE-OUTAGE','jira_ticket','2026-10-12T09:09:00+05:30',supports=['ROUTE-SCHEMA'])
record('Route API 422 logs','LOG','09:15:20 422 SchemaError carrier_zone_code expected string; v2 edge workers still active.', 'ROUTE-OUTAGE','application_log','2026-10-12T09:15:20+05:30',supports=['ROUTE-SCHEMA'])
record('Routing DB CPU plot','METRIC','CPU rose from 37% to 93% at 09:20, five minutes after 422 spike.', 'ROUTE-OUTAGE','metric_snapshot','2026-10-12T09:20:00+05:30',supports=['ROUTE-CPU'],confidence=.63)
record('Route edge distributed trace','TRACE','v2 region-edge -> route API -> schema v3 failure -> retry -> CPU increase.', 'ROUTE-OUTAGE','trace','2026-10-12T09:18:00+05:30',supports=['ROUTE-SCHEMA'],refutes=['ROUTE-CPU'])
record('SRE on-call Slack assertion','SLACK','On-call: CPU is pegged, suspect connection pool; investigation unconfirmed.', 'ROUTE-OUTAGE','slack_message','2026-10-12T09:22:00+05:30',supports=['ROUTE-CPU'],confidence=.51)
record('Platform Slack review','SLACK','Platform: the edge clients are still on v2; v3 change was deployed before compatibility test.', 'ROUTE-OUTAGE','slack_message','2026-10-12T09:25:00+05:30',supports=['ROUTE-SCHEMA'])
record('Route migration policy excerpt','POLICY','POL-AST-ROUTE: schema changes must be backward compatible until fleet version > 99%.', 'ROUTE-OUTAGE','policy_document','2026-10-12T09:10:00+05:30',supports=['ROUTE-SCHEMA'])
record('Historical route postmortem','POSTMORTEM','May incident: version drift during schema rollout. Historical match requires investigation.', 'OLD-MIGRATION','postmortem','2026-05-12T11:00:00+05:30')
record('Carrier retry backlog metric','METRIC','Carrier gateway retry backlog reached 18000 while route API returned 422.', 'CARRIER-LAG','metric_snapshot','2026-10-12T09:47:00+05:30',supports=['CARRIER-TIME'])
record('Carrier incident partner update','SLACK','Partner account update: no upstream carrier outage confirmed; requests wait inside gateway.', 'CARRIER-LAG','slack_message','2026-10-12T09:52:00+05:30',refutes=['CARRIER-VENDOR'])
record('Warehouse handheld errors','LOG','Warehouse handheld devices cannot reserve dispatch slots while route orchestration is unavailable.', 'WAREHOUSE-QUEUE','application_log','2026-10-12T09:55:00+05:30')
record('Carrier confirmation sample','DB','Late confirmations reached payout ledger 90 minutes behind booking timestamp.', 'PAYOUT-DRIFT','database_snapshot','2026-10-12T10:11:00+05:30',supports=['PAYOUT-EVENT'])
record('Fraud alert sample','AUDIT','No increase in payout fraud flags during the confirmation lag window.', 'PAYOUT-DRIFT','audit_log','2026-10-12T10:20:00+05:30',refutes=['PAYOUT-FRAUD'])
record('Old escalation roster','HR','Legacy Integrations team retired July 2026; current carrier escalation approver missing.', 'PARTNER-SLA','hr_record','2026-10-12T10:19:00+05:30',supports=['OWNER-RETIRED'])
record('Legacy carrier escalation ticket','JIRA','AST-3611: unresolved replacement owner for retired adapter.', 'PARTNER-SLA','jira_ticket','2026-10-12T10:21:00+05:30',supports=['OWNER-RETIRED'])
record('Consent registry audit','AUDIT','Customer export job was triggered without current partner consent grant.', 'SECURITY-EXPORT','audit_log','2026-10-10T13:02:00+05:30',supports=['PRIVACY-BLOCK'])
record('Privacy policy excerpt','POLICY','POL-AST-PRIVACY requires consent verification before customer export for analytics.', 'SECURITY-EXPORT','policy_document','2026-10-10T13:04:00+05:30',supports=['PRIVACY-BLOCK'],refutes=['PRIVACY-EXEMPT'])
record('Forecast bias dashboard','METRIC','Forecast v3 deviation rose after missing shipment confirmations impacted training aggregate.', 'FORECAST-BIAS','metric_snapshot','2026-10-12T11:08:00+05:30')
record('Duplicate billing issue','JIRA','AST-5011: two teams delivered independent credit-note automation with overlapping acceptance.', 'INVOICE-DUP','jira_ticket','2026-10-09T15:05:00+05:30')
record('Agent action retry ledger','AUDIT','Retry attempt on route fallback after uncertain completion; lock owner missing.', 'AGENT-RETRY','audit_log','2026-10-12T11:35:00+05:30')
record('Partner CRM export comparison','CRM','Partner status reflected old SLA owner after team retirement.', 'PARTNER-SLA','crm_record','2026-10-12T10:26:00+05:30')
record('Route DB access key event','AUDIT','Service credential change not propagated to weekend on-call roster.', 'ACCESS-EXPIRED','audit_log','2026-08-25T08:03:00+05:30')
record('Dispatch queue backlog','METRIC','Picking backlog increased 5600 jobs; dependent scheduling service returns timeout.', 'WAREHOUSE-QUEUE','metric_snapshot','2026-10-12T09:57:00+05:30')
record('SLA warehouse audit','DB','Fulfilled shipments absent from tracking feed; dashboard is stale.', 'SLA-RECON','database_snapshot','2026-10-12T11:28:00+05:30')
# Link source records to code, policy, project and change for multi-hop lineages.
p.e('EVD-AST-0001','ABOUT','CHG-AST-ROUTE-V3')
p.e('EVD-AST-0002','ABOUT','PROJ-AST-ROUTE2')
p.e('EVD-AST-0008','ABOUT','POL-AST-ROUTE')
p.e('EVD-AST-0009','SIMILAR_TO','EVD-AST-0001',at='2026-10-12T10:00:00+05:30',confidence=.52,relationship_kind='candidate_similarity_only')
p.e('CLM-AST-ROUTE-SCHEMA','ABOUT','CHG-AST-ROUTE-V3')
p.e('CLM-AST-ROUTE-CPU','ABOUT','SYS-AST-ROUTE-DB')

# Inter-incident dependencies / correlated but not automatically established root cause.
for source,target in [('ROUTE-OUTAGE','CARRIER-LAG'),('ROUTE-OUTAGE','WAREHOUSE-QUEUE'),('CARRIER-LAG','PAYOUT-DRIFT'),('CARRIER-LAG','PARTNER-SLA'),('PAYOUT-DRIFT','INVOICE-DUP')]:
 p.e('INC-AST-'+source,'AFFECTS','INC-AST-'+target,at='2026-10-12T12:30:00+05:30',confidence=.7,relationship_kind='candidate_propagation')

# Decisions from earlier incidents, not a pre-approved outcome of the active route outage.
p.n('DEC-AST-MAY-ROLLBACK','Decision','May routing rollback approval',status='APPROVED',statement='Rollback historical v2 route schema migration.',decision_type='incident_remediation',rationale_summary='Compatibility evidence from May incident.')
p.e('DEC-AST-MAY-ROLLBACK','BASED_ON','INC-AST-OLD-MIGRATION')
p.e('DEC-AST-MAY-ROLLBACK','APPROVED_BY',people_by_team['CORE'][0])
p.n('DEC-AST-OWNER-REVIEW','Decision','Require reviewed ownership transfer',status='PROPOSED',statement='Hold carrier policy escalation until a new accountable owner is approved.',decision_type='ownership_governance',approval_required=True)
p.e('DEC-AST-OWNER-REVIEW','BASED_ON','CLM-AST-OWNER-RETIRED')
p.e('DEC-AST-OWNER-REVIEW','BASED_ON','POL-AST-NEW-SLA')

# Decisions intentionally connect multiple systems and business functions.
p.e('DEC-AST-MAY-ROLLBACK','AFFECTS','SYS-AST-ROUTE-API',at='2026-05-12T12:00:00+05:30')
p.e('DEC-AST-MAY-ROLLBACK','AFFECTS','SYS-AST-ROUTE-DB',at='2026-05-12T12:00:00+05:30')
p.e('DEC-AST-OWNER-REVIEW','AFFECTS','SYS-AST-OLD-CARRIER',at='2026-10-12T12:00:00+05:30')
p.e('DEC-AST-OWNER-REVIEW','AFFECTS','SYS-AST-CARRIER-GW',at='2026-10-12T12:00:00+05:30')

# Event lineage; historical and concurrent with ongoing investigation.
EVENTS=[('DEPLOY','DEPLOYMENT_STARTED','ROUTE-OUTAGE','Routing schema v3 rollout started','2026-10-12T09:05:00+05:30'),
 ('FIRST-422','APPLICATION_ERROR','ROUTE-OUTAGE','First 422 edge schema errors','2026-10-12T09:15:00+05:30'),
 ('CPU','METRIC_ALARM','ROUTE-OUTAGE','Route DB CPU spike after retry loop','2026-10-12T09:20:00+05:30'),
 ('CARRIER','SITUATION_OPENED','CARRIER-LAG','Carrier label backlog declared','2026-10-12T09:42:00+05:30'),
 ('WAREHOUSE','SITUATION_OPENED','WAREHOUSE-QUEUE','Picking queue stopped','2026-10-12T09:47:00+05:30'),
 ('PAYOUT','SITUATION_OPENED','PAYOUT-DRIFT','Finance reconciliation mismatch surfaced','2026-10-12T10:05:00+05:30'),
 ('OWNER','OWNERSHIP_GAP','PARTNER-SLA','Retired escalation owner found','2026-10-12T10:18:00+05:30'),
 ('EXPORT','UNAPPROVED_EXPORT','SECURITY-EXPORT','Consent gate missing on customer data export','2026-10-10T13:02:00+05:30'),
 ('AGENT-FAILED','ACTION_FAILED','AGENT-RETRY','Agent action failed and awaits manual review','2026-10-12T11:35:00+05:30')]
for code,kind,inc,text,at in EVENTS:
 eid=p.n('EVT-AST-'+code,'Event',text,at=at,event_type=kind,summary=text,occurred_at=at)
 p.e(eid,'ABOUT','INC-AST-'+inc,at=at)
for a,b in zip([x[0] for x in EVENTS[:7]],[x[0] for x in EVENTS[1:7]]):
 p.e('EVT-AST-'+a,'BEFORE','EVT-AST-'+b,at='2026-10-12T12:00:00+05:30')

# Organizational commitments and ongoing debt.
for code,title,team,target,due in [('ROUTE-VERIFY','Complete v2/v3 mixed-version test','CORE','ROUTE-API','2026-10-11T18:00:00+05:30'),('SLA-OWNER','Appoint replacement carrier policy owner','PARTNERS','OLD-CARRIER','2026-09-01T18:00:00+05:30'),('PAYOUT-AUDIT','Reconcile carrier ledger','TREASURY','PAYOUT','2026-10-15T18:00:00+05:30'),('MEMORY-RET','Review agent memory compaction rules','ENABLE','DOCSEARCH','2026-10-20T18:00:00+05:30'),('CONSENT','Close consent verification gaps','PRIVACY','CUST-ETL','2026-10-15T18:00:00+05:30')]:
 cid=p.n('COM-AST-'+code,'Commitment',title,status='OPEN',due_at=due,summary=title)
 p.e('TEAM-'+team,'COMMITTED_TO',cid)
 p.e(cid,'ABOUT','SYS-AST-'+target)

# Coordination scaffolding: the pack models initial state, never pretends to execute tools.
AGENTS=[('INVESTIGATOR','Incident Investigator','INVESTIGATOR',['INVESTIGATE','ACQUIRE_EVIDENCE']),('DEPENDENCY','Dependency Analyst','DEPENDENCY_ANALYST',['INVESTIGATE']),
 ('POLICY','Policy Verifier','VERIFIER',['VERIFY_CLAIM','RESOLVE_CONFLICT','VALIDATE_POLICY']),('EVIDENCE','Evidence Collector','INVESTIGATOR',['ACQUIRE_EVIDENCE']),
 ('REMEDIATION','Recovery Planner','REMEDIATION_WORKER',['PREPARE_ACTION','VALIDATE_OUTCOME']),('FINANCE','Ledger Investigator','INVESTIGATOR',['INVESTIGATE']),
 ('SECURITY','Consent Investigator','VERIFIER',['VERIFY_CLAIM','VALIDATE_POLICY']),('MEMORY','Agent Memory Auditor','VERIFIER',['VERIFY_CLAIM','VALIDATE_POLICY']),
 ('HANDOFF','Handoff Coordinator','VERIFIER',['RESOLVE_CONFLICT']),('EXPERT','Expert Locator','INVESTIGATOR',['INVESTIGATE']),
 ('OPS','Fulfilment Operations Analyst','DEPENDENCY_ANALYST',['INVESTIGATE']),('POSTMORTEM','Knowledge Historian','INVESTIGATOR',['INVESTIGATE'])]
for code,name,kind,supported in AGENTS:
 pid=p.n('AGENT-AST-'+code,'Agent',name,status='ACTIVE',availability='AVAILABLE',agent_type=kind,
           supported_task_types=','.join(supported),permissions='READ_GRAPH,READ_EVIDENCE,WRITE_FINDING,CHECKPOINT',
           capabilities='GRAPH_TRAVERSAL,EVIDENCE_RETRIEVAL,COORDINATION',fixture_only=True)
 p.e(pid,'PART_OF','PROJ-AST-OPS-AI')
for code,agent,tool in [('INVESTIGATOR','INVESTIGATOR','TRACES'),('EVIDENCE','EVIDENCE','LOGS'),('POLICY','POLICY','POLICIES'),('EXPERT','EXPERT','OWNERSHIP'),('DEPENDENCY','DEPENDENCY','OWNERSHIP'),('SECURITY','SECURITY','SECURITY'),('POSTMORTEM','POSTMORTEM','TICKETS')]:
 p.e('AGENT-AST-'+agent,'REQUIRES','TOOL-AST-'+tool)

p.n('PLAN-AST-RECOVERY','Plan','Cross-system route incident response',status='DRAFT',plan_type='INCIDENT_RECOVERY',priority='P0',fixture_only=True)
p.e('PLAN-AST-RECOVERY','ADDRESSES','INC-AST-ROUTE-OUTAGE')
TASKS=[('ROUTE-SCOPE','Investigate route edge failures','INVESTIGATOR','INVESTIGATE','ROUTE-OUTAGE','OPEN'),
 ('ROUTE-EVIDENCE','Collect code, logs and traces','EVIDENCE','ACQUIRE_EVIDENCE','ROUTE-OUTAGE','OPEN'),
 ('ROUTE-BLAST','Find affected downstream systems','DEPENDENCY','INVESTIGATE','ROUTE-OUTAGE','OPEN'),
 ('ROUTE-POLICY','Validate compatibility and rollback policy','POLICY','VALIDATE_POLICY','ROUTE-OUTAGE','OPEN'),
 ('ROUTE-APPROVAL','Prepare approved rollback proposal','REMEDIATION','PREPARE_ACTION','ROUTE-OUTAGE','BLOCKED'),
 ('CARRIER-BACKLOG','Investigate carrier label queue','OPS','INVESTIGATE','CARRIER-LAG','OPEN'),
 ('WAREHOUSE-QUEUE','Investigate warehouse picking backlog','OPS','INVESTIGATE','WAREHOUSE-QUEUE','OPEN'),
 ('FINANCE-RECON','Explain payout drift','FINANCE','INVESTIGATE','PAYOUT-DRIFT','OPEN'),
 ('CONSENT-CHECK','Verify customer export consent','SECURITY','VALIDATE_POLICY','SECURITY-EXPORT','OPEN'),
 ('OWNER-TRACE','Find historical escalation ownership','EXPERT','INVESTIGATE','PARTNER-SLA','OPEN'),
 ('OWNER-APPROVE','Review owner transfer','POLICY','VALIDATE_POLICY','PARTNER-SLA','BLOCKED'),
 ('HISTORY','Find similar historical migrations','POSTMORTEM','INVESTIGATE','OLD-MIGRATION','OPEN'),
 ('MEMORY-CHECK','Audit promoted memory provenance','MEMORY','VERIFY_CLAIM','ROUTE-OUTAGE','OPEN'),
 ('AGENT-RETRY','Investigate uncertain action retry','INVESTIGATOR','INVESTIGATE','AGENT-RETRY','OPEN'),
 ('DEADLOCK-A','Wait for schema review','INVESTIGATOR','INVESTIGATE','ROUTE-OUTAGE','BLOCKED'),
 ('DEADLOCK-B','Wait for graph impact review','POLICY','VALIDATE_POLICY','ROUTE-OUTAGE','BLOCKED'),
 ('HANDOFF','Validate incomplete analyst handoff','HANDOFF','RESOLVE_CONFLICT','ROUTE-OUTAGE','BLOCKED'),
 ('PAYOUT-CONFIRM','Verify payout confirmations','FINANCE','INVESTIGATE','PAYOUT-DRIFT','OPEN'),
 ('CARRIER-CONFIRM','Find original carrier receipt','EVIDENCE','ACQUIRE_EVIDENCE','CARRIER-LAG','OPEN'),
 ('ALERT-TRIAGE','Review cross-business alerts','INVESTIGATOR','INVESTIGATE','SLA-RECON','OPEN'),
 ('ESCALATION','Escalate customer facing outage','POLICY','VALIDATE_POLICY','PARTNER-SLA','OPEN'),
 ('SNAPSHOT','Collect access audit snapshot','EVIDENCE','ACQUIRE_EVIDENCE','ACCESS-EXPIRED','OPEN'),
 ('FORECAST-DRIFT','Investigate shipment forecast bias','DEPENDENCY','INVESTIGATE','FORECAST-BIAS','OPEN'),
 ('CREDIT-DUP','Identify duplicate credit note projects','EXPERT','INVESTIGATE','INVOICE-DUP','OPEN')]
for code,title,agent,tasktype,inc,status in TASKS:
 tid='TASK-AST-'+code
 p.n(tid,'Task',title,task_type=tasktype,status=status,priority='P0' if code.startswith('ROUTE') else 'P1',
     fixture_only=True,description=title)
 p.e(tid,'ABOUT','INC-AST-'+inc)
 p.e(tid,'ASSIGNED_TO','AGENT-AST-'+agent)
 p.e('AGENT-AST-'+agent,'CANDIDATE_FOR',tid)
 p.e('PLAN-AST-RECOVERY','PLAN_HAS_TASK',tid)
for a,b in [('ROUTE-APPROVAL','ROUTE-POLICY'),('ROUTE-APPROVAL','ROUTE-EVIDENCE'),('ROUTE-POLICY','ROUTE-EVIDENCE'),('OWNER-APPROVE','OWNER-TRACE'),('HANDOFF','ROUTE-SCOPE'),('DEADLOCK-A','DEADLOCK-B'),('DEADLOCK-B','DEADLOCK-A'),('PAYOUT-CONFIRM','CARRIER-CONFIRM')]:
 p.e('TASK-AST-'+a,'BLOCKED_BY','TASK-AST-'+b)
# Checkpoint and handoff are *synthetic past snapshots*, not fresh agent execution.
p.n('EXEC-AST-ROUTE-PAUSED','Execution','Route analyst interrupted run',status='PAUSED',started_at='2026-10-12T10:00:00+05:30',
    fixture_only=True,simulation_record=True,agent_id='AGENT-AST-INVESTIGATOR')
p.e('TASK-AST-ROUTE-SCOPE','HAS_EXECUTION','EXEC-AST-ROUTE-PAUSED')
p.e('EXEC-AST-ROUTE-PAUSED','PERFORMED_BY','AGENT-AST-INVESTIGATOR')
p.n('CHECK-AST-ROUTE-1','Checkpoint','Route evidence read checkpoint',status='SAVED',sequence_number=1,
    memory_summary='Read first 4 route evidence records; schema clue remains unverified.',fixture_only=True,simulation_record=True)
p.e('EXEC-AST-ROUTE-PAUSED','HAS_CHECKPOINT','CHECK-AST-ROUTE-1')
p.e('CHECK-AST-ROUTE-1','BASED_ON','EVD-AST-0001')
p.e('CHECK-AST-ROUTE-1','BASED_ON','EVD-AST-0003')
p.n('HANDOFF-AST-MISSING','Handoff','Incomplete analyst to policy handoff',status='INVALID',
    required_artifacts='evidence_ids,conclusion,open_questions',provided_artifacts='conclusion,open_questions',
    reason='evidence_ids missing',fixture_only=True,simulation_record=True)
p.e('HANDOFF-AST-MISSING','HANDOFF_FOR','TASK-AST-HANDOFF')
p.e('HANDOFF-AST-MISSING','ASSIGNED_TO','AGENT-AST-POLICY')
p.n('HANDOFF-AST-VALID','Handoff','Validated agent recovery handoff',status='VALID',required_artifacts='evidence_ids,conclusion,open_questions',
    provided_artifacts='evidence_ids,conclusion,open_questions',fixture_only=True,simulation_record=True)
p.e('HANDOFF-AST-VALID','HANDOFF_FOR','TASK-AST-ROUTE-POLICY')
p.e('HANDOFF-AST-VALID','BASED_ON','EVD-AST-0003')
# Memory promotion conflict: old memory is not automatically authoritative.
p.n('FIND-AST-CPU-MEMORY','Finding','Cached database CPU explanation',status='PROPOSED',confidence=.42,
    summary='Agent retained CPU hypothesis before newer trace evidence arrived.',fixture_only=True,memory_state='STALE')
p.e('FIND-AST-CPU-MEMORY','BASED_ON','EVD-AST-0004')
p.e('FIND-AST-CPU-MEMORY','ABOUT','CLM-AST-ROUTE-CPU')
p.n('FIND-AST-SCHEMA','Finding','New trace-based schema finding',status='PROPOSED',confidence=.81,
    summary='Trace indicates version incompatibility; still needs evidence validation.',fixture_only=True,memory_state='PENDING_REVIEW')
p.e('FIND-AST-SCHEMA','BASED_ON','EVD-AST-0005')
p.e('FIND-AST-SCHEMA','ABOUT','CLM-AST-ROUTE-SCHEMA')
p.e('FIND-AST-SCHEMA','CONTRADICTS','FIND-AST-CPU-MEMORY')
p.n('WB-AST-REVIEW','WorkBranch','Analyst review branch',status='PAUSED',branch_type='EVIDENCE_REVIEW',fixture_only=True)
p.e('EXEC-AST-ROUTE-PAUSED','HAS_BRANCH','WB-AST-REVIEW')
p.e('WB-AST-REVIEW','CONTAINS','FIND-AST-SCHEMA')
p.n('CMP-AST-ROUTE','CompactionRecord','Agent memory compaction snapshot',status='PENDING_REVIEW',
    summary='Preserve evidence lineage; unresolved hypothesis must not become verified fact.',fixture_only=True)
p.e('EXEC-AST-ROUTE-PAUSED','HAS_COMPACTION','CMP-AST-ROUTE')
p.e('CMP-AST-ROUTE','BASED_ON','CHECK-AST-ROUTE-1')
p.n('LOCK-AST-ROLLBACK','Lock','Route recovery action lock',status='HELD',resource_id='SYS-AST-ROUTE-API',lease_until='2026-10-12T13:00:00+05:30',fixture_only=True)
p.e('LOCK-AST-ROLLBACK','LOCKS','SYS-AST-ROUTE-API')
for code,title,system in [('ROLLBACK','Propose route schema rollback','ROUTE-DB'),('VERIFY','Verify edge client compatibility','ROUTE-API'),('RESTORE','Restore dispatch scheduling','DISPATCH')]:
 p.n('ACT-AST-'+code,'Action',title,status='PROPOSED',action_type={'ROLLBACK':'rollback','VERIFY':'verification','RESTORE':'recovery'}[code],
     idempotency_key=f'asteria:v1:{code.lower()}:route-incident',approval_required=code!='VERIFY',
     fixture_only=True,simulation_record=True)
 p.e('ACT-AST-'+code,'ABOUT','INC-AST-ROUTE-OUTAGE')
 p.e('ACT-AST-'+code,'ABOUT','SYS-AST-'+system)
p.e('POL-AST-ROLLBACK','GOVERNS','ACT-AST-ROLLBACK')
p.e('POL-AST-ACTION','GOVERNS','ACT-AST-RESTORE')
p.n('ATT-AST-RETRY-1','ActionAttempt','Simulated uncertain action retry',status='FAILED',idempotency_key='asteria:v1:rollback:route-incident',
    failure_reason='missing approval; must not execute',fixture_only=True,simulation_record=True)
p.e('ACT-AST-ROLLBACK','HAS_ATTEMPT','ATT-AST-RETRY-1')
p.e('ATT-AST-RETRY-1','ABOUT','INC-AST-AGENT-RETRY')
p.n('OUT-AST-MAY','Outcome','Historical migration rollback outcome',status='OBSERVED',summary='May migration rollback stabilized routing; not a guarantee for October.',fixture_only=True)
p.e('DEC-AST-MAY-ROLLBACK','HAS_OUTCOME','OUT-AST-MAY')
# Other graph reasoning problems.
p.e('PROJ-AST-BILL-DUP1','COLLABORATES_WITH','PROJ-AST-BILL-DUP2',confidence=.7,reason='overlapping refund automation scope')
p.e('SYS-AST-REGION-EDGE','DEPENDS_ON','SYS-AST-OLD-CARRIER',at='2025-06-01T00:00:00+05:30',end='2026-08-01T00:00:00+05:30')

# Explicit questions are intentionally left unanswered in the graph, rather than silently
# converted to findings or synthetic "facts"; the agents must pursue provenance.
QUESTIONS=[('MIXED-VERSIONS','Which regional clients still emit schema v2?','ROUTE-OUTAGE','TOOL-AST-LOGS'),
 ('ROLLBACK-PROOF','Has route rollback received a human policy approval?','ROUTE-OUTAGE','TOOL-AST-POLICIES'),
 ('CARRIER-RECEIPT','Do upstream carriers acknowledge the queued labels?','CARRIER-LAG','TOOL-AST-TICKETS'),
 ('OWNER-APPROVAL','Who has legal authority to approve replacement carrier owner?','PARTNER-SLA','TOOL-AST-OWNERSHIP'),
 ('DATA-CONSENT','Is there a valid consent record for all exported partners?','SECURITY-EXPORT','TOOL-AST-SECURITY'),
 ('FINANCE-LEDGER','Which payout totals differ between tracking and ledger?','PAYOUT-DRIFT','TOOL-AST-DB'),
 ('AGENT-CHECKPOINT','Can interrupted agent execution be resumed safely from this checkpoint?','AGENT-RETRY','TOOL-AST-SECURITY'),
 ('FORECAST-RETRAIN','Did the model retrain with incomplete shipment labels?','FORECAST-BIAS','TOOL-AST-DB')]
for code,title,incident,tool in QUESTIONS:
 q='Q-AST-'+code
 p.n(q,'Question',title,status='OPEN',question=title,knowledge_gap=True)
 p.e(q,'ABOUT','INC-AST-'+incident)
 p.e(q,'REQUIRES',tool)

# An HR/CRM person reconciliation conflict: *two candidates*, neither promoted.
p.n('SRCREC-AST-IDENTITY','SourceRecord','Unresolved partner contact: R. Menon',
    source_type='HR',source_key='asteria-v1/hr/contact-r-menon',source_entity_id='SYN-HR-CONTACT-022',
    content='R. Menon listed as integration approver; both Ritika Menon and Mira Sachdeva have overlapping records.',
    fixture_only=True,ingestion_status='QUARANTINED',checksum='fixture-id-022')
p.e('SRCREC-AST-IDENTITY','DERIVED_FROM','DS-AST-HR')
p.e('SRCREC-AST-IDENTITY','CANDIDATE_MATCH','PERSON-AST-062',confidence=.53,matching_basis='name/role; unresolved')
p.e('SRCREC-AST-IDENTITY','CANDIDATE_MATCH','PERSON-AST-028',confidence=.39,matching_basis='team alias; unresolved')
p.e('SRCREC-AST-IDENTITY','ABOUT','INC-AST-PARTNER-SLA')

# Additional historical agent records deliberately contrast fail/resume and coordination
# without pretending any live automation has already run in this session.
p.n('EXEC-AST-FINANCE-FAILED','Execution','Finance investigation source timeout',status='FAILED',
    fixture_only=True,simulation_record=True,failure_reason='carrier reconciliation query timed out',
    started_at='2026-10-12T10:18:00+05:30')
p.e('TASK-AST-FINANCE-RECON','HAS_EXECUTION','EXEC-AST-FINANCE-FAILED')
p.e('EXEC-AST-FINANCE-FAILED','PERFORMED_BY','AGENT-AST-FINANCE')
p.n('CHECK-AST-FINANCE-1','Checkpoint','Finance query checkpoint',status='SAVED',sequence_number=1,
    memory_summary='Saved carrier ledger sample; cannot infer fraud from data lag.',fixture_only=True,simulation_record=True)
p.e('EXEC-AST-FINANCE-FAILED','HAS_CHECKPOINT','CHECK-AST-FINANCE-1')
p.e('CHECK-AST-FINANCE-1','BASED_ON','EVD-AST-0013')
p.n('EXEC-AST-FINANCE-RESUME','Execution','Finance ledger investigation resumed',status='PAUSED',
    fixture_only=True,simulation_record=True,resumed_from='CHECK-AST-FINANCE-1',
    started_at='2026-10-12T10:32:00+05:30')
p.e('TASK-AST-FINANCE-RECON','HAS_EXECUTION','EXEC-AST-FINANCE-RESUME')
p.e('EXEC-AST-FINANCE-RESUME','HAS_CHECKPOINT','CHECK-AST-FINANCE-1')
p.e('EXEC-AST-FINANCE-RESUME','PERFORMED_BY','AGENT-AST-FINANCE')
p.n('FIND-AST-FINANCE-TEMP','Finding','Payout delay vs fraud hypothesis',status='PROPOSED',confidence=.64,
    summary='Late confirmations appear plausible; approval needed before claiming causality.',fixture_only=True,memory_state='PENDING_REVIEW')
p.e('FIND-AST-FINANCE-TEMP','BASED_ON','EVD-AST-0013')
p.e('FIND-AST-FINANCE-TEMP','ABOUT','CLM-AST-PAYOUT-EVENT')
p.n('WB-AST-FINANCE','WorkBranch','Finance scoped evidence branch',status='PAUSED',fixture_only=True)
p.e('EXEC-AST-FINANCE-RESUME','HAS_BRANCH','WB-AST-FINANCE')
p.e('WB-AST-FINANCE','CONTAINS','FIND-AST-FINANCE-TEMP')
p.n('CHECK-AST-POLICY-1','Checkpoint','Policy verifier handoff checkpoint',status='SAVED',sequence_number=1,
    memory_summary='Policy version review not complete; no valid approval recorded.',fixture_only=True,simulation_record=True)
p.e('HANDOFF-AST-VALID','BASED_ON','CHECK-AST-POLICY-1')
p.e('CHECK-AST-POLICY-1','BASED_ON','POL-AST-ROLLBACK')
p.n('EXEC-AST-POLICY-WAIT','Execution','Policy verifier awaits signoff',status='BLOCKED',fixture_only=True,simulation_record=True)
p.e('TASK-AST-ROUTE-POLICY','HAS_EXECUTION','EXEC-AST-POLICY-WAIT')
p.e('EXEC-AST-POLICY-WAIT','HAS_CHECKPOINT','CHECK-AST-POLICY-1')
p.e('EXEC-AST-POLICY-WAIT','PERFORMED_BY','AGENT-AST-POLICY')
p.n('HANDOFF-AST-FINANCE','Handoff','Carrier evidence to finance investigator',status='VALID',
    required_artifacts='evidence_ids,conclusion,open_questions',provided_artifacts='evidence_ids,conclusion,open_questions',
    fixture_only=True,simulation_record=True)
p.e('HANDOFF-AST-FINANCE','HANDOFF_FOR','TASK-AST-FINANCE-RECON')
p.e('HANDOFF-AST-FINANCE','BASED_ON','EVD-AST-0013')
p.n('ACT-AST-CARRIER-RETRY','Action','Retry queued carrier labels',status='PROPOSED',action_type='verification',
    approval_required=True,idempotency_key='asteria:v1:carrier:retry',fixture_only=True)
p.e('ACT-AST-CARRIER-RETRY','ABOUT','INC-AST-CARRIER-LAG')
p.e('POL-AST-CARRIER','GOVERNS','ACT-AST-CARRIER-RETRY')
p.n('ATT-AST-CARRIER-1','ActionAttempt','Carrier retry declined for missing consent',status='FAILED',fixture_only=True,
    failure_reason='approval required',idempotency_key='asteria:v1:carrier:retry',simulation_record=True)
p.e('ACT-AST-CARRIER-RETRY','HAS_ATTEMPT','ATT-AST-CARRIER-1')
p.n('PLAN-AST-CARRIER','Plan','Carrier label recovery plan',status='DRAFT',fixture_only=True)
p.e('PLAN-AST-CARRIER','ADDRESSES','INC-AST-CARRIER-LAG')
for code in ['CARRIER-BACKLOG','CARRIER-CONFIRM']:
 p.e('PLAN-AST-CARRIER','PLAN_HAS_TASK','TASK-AST-'+code)
p.n('PLAN-AST-CONSENT','Plan','Export consent review plan',status='DRAFT',fixture_only=True)
p.e('PLAN-AST-CONSENT','ADDRESSES','INC-AST-SECURITY-EXPORT')
p.e('PLAN-AST-CONSENT','PLAN_HAS_TASK','TASK-AST-CONSENT-CHECK')

# Contract registry: paths always grounded in explicit seeded edges; golden details not seeded.
def s(key,track,title,summary,entries,focus,tests,paths,props=None,absent=None,temporal=None,reason=''):
 p.scenario(key,track,title,summary,entries,focus,tests)
 p.gold(key,paths,props,absent,temporal,reason)
S='COMPANY_BRAIN';A='CONNECTED_AGENTS';M='AGENT_MEMORY_COORDINATION'
s('AST-CB-01',S,'Hidden dependency blast radius','Explore the blast radius from shared Route DB.', ['SYS-AST-ROUTE-DB'],['SYS-AST-DISPATCH','SYS-AST-PICK','SYS-AST-REGION-EDGE'],
 ['Which operational systems depend on Route DB?','Explain the dependency paths affecting dispatch and picking.'],
 [['SYS-AST-DISPATCH','SYS-AST-ROUTE-API','SYS-AST-ROUTE-DB'],['SYS-AST-PICK','SYS-AST-ROUTE-API','SYS-AST-ROUTE-DB']])
s('AST-CB-02',S,'Conflicting outage claims','Investigate competing CPU and compatibility hypotheses.', ['INC-AST-ROUTE-OUTAGE'],['CLM-AST-ROUTE-CPU','CLM-AST-ROUTE-SCHEMA'],
 ['What evidence supports each hypothesis?','Which claim has stronger evidence, and what remains unverified?'],
 [['EVD-AST-0001','CLM-AST-ROUTE-SCHEMA'],['EVD-AST-0005','CLM-AST-ROUTE-CPU']],
 reason='One evidence SUPPORTS schema claim, another REFUTES CPU hypothesis; do not leak final root cause.')
s('AST-CB-03',S,'Time-aware ownership and retiring team','Find the original owner of the orphaned carrier adapter.', ['SYS-AST-OLD-CARRIER'],['TEAM-LEGACY','PERSON-AST-LEGACY'],
 ['Who owned the retired carrier adapter in 2025?','Why is its current ownership unresolved?'],
 [['TEAM-LEGACY','SYS-AST-OLD-CARRIER']],
 absent=[['TEAM-CARRIER','OWNS','SYS-AST-OLD-CARRIER']],
 temporal=[{'source':'TEAM-LEGACY','type':'OWNS','target':'SYS-AST-OLD-CARRIER','active_at':'2026-06-01T00:00:00+05:30','inactive_at':'2026-10-12T00:00:00+05:30'}])
s('AST-CB-04',S,'Expert discovery across teams','Find qualified routing expertise after staff departure.', ['SYS-AST-ROUTE-API'],['PERSON-AST-001','PERSON-AST-005'],
 ['Who can help Route API and which teams know adjacent systems?'],
 [['TEAM-CORE','SYS-AST-ROUTE-API'],[people_by_team['CORE'][0],'SYS-AST-ROUTE-API']])
s('AST-CB-05',S,'Historical decision genealogy','Connect May incident to a real past rollback decision.', ['INC-AST-OLD-MIGRATION'],['DEC-AST-MAY-ROLLBACK','OUT-AST-MAY'],
 ['What was decided after the May migration, and what evidence was used?'],
 [['DEC-AST-MAY-ROLLBACK','INC-AST-OLD-MIGRATION'],['DEC-AST-MAY-ROLLBACK','OUT-AST-MAY']])
s('AST-CB-06',S,'Policy version evolution','Explain how a retired SLA policy differs from its replacement.', ['POL-AST-NEW-SLA'],['POL-AST-OLD-SLA','INC-AST-PARTNER-SLA'],
 ['Which SLA policy is current and why is old escalation ownership a problem?'],
 [['POL-AST-NEW-SLA','POL-AST-OLD-SLA']],
 temporal=[{'source':'POL-AST-OLD-SLA','type':'GOVERNS','target':'SYS-AST-OLD-CARRIER','active_at':'2026-06-01T00:00:00+05:30','inactive_at':'2026-10-12T00:00:00+05:30'}])
s('AST-CB-07',S,'Duplicate cross-team initiatives','Find two teams automating the same billing issue.', ['PROJ-AST-BILL-DUP1'],['PROJ-AST-BILL-DUP2','SYS-AST-BILLING'],
 ['Which teams built overlapping credit note automation?'],
 [['PROJ-AST-BILL-DUP1','PROJ-AST-BILL-DUP2'],['PROJ-AST-BILL-DUP2','SYS-AST-BILLING']])
s('AST-CB-08',S,'Unregistered sensitive dependency','Detect the analytics dashboard accessing the financial ledger.', ['SYS-AST-ANALYTICS'],['SYS-AST-LEDGER','POL-AST-ACCESS'],
 ['Show unauthorized or uncatalogued cross-domain data access dependencies.'],
 [['SYS-AST-ANALYTICS','SYS-AST-LEDGER']],
 props=[{'id':'SYS-AST-ANALYTICS','field':'name','equals':'Operations BI'}])
s('AST-AA-01',A,'Connected outage investigation','Investigate route migration with commit, Jira, logs and traces.', ['INC-AST-ROUTE-OUTAGE'],['CHG-AST-ROUTE-V3','EVD-AST-0001','EVD-AST-0005'],
 ['Investigate INC-AST-ROUTE-OUTAGE and cite traceable evidence.'],
 [['EVD-AST-0001','SRCREC-AST-0001','DS-AST-GITHUB'],['EVD-AST-0005','CLM-AST-ROUTE-CPU']])
s('AST-AA-02',A,'Multi-system blast radius and downstream tasks','Assess carrier and warehouse effects of routing outage.', ['SYS-AST-ROUTE-DB'],['INC-AST-WAREHOUSE-QUEUE','INC-AST-CARRIER-LAG','TASK-AST-ROUTE-BLAST'],
 ['Find which fulfilment functions are exposed to Route DB failures.'],
 [['SYS-AST-CARRIER-GW','SYS-AST-ROUTE-API','SYS-AST-ROUTE-DB'],['SYS-AST-WMS','SYS-AST-PICK','SYS-AST-ROUTE-API','SYS-AST-ROUTE-DB']])
s('AST-AA-03',A,'Evidence-backed governed rollback','Propose rollback only after policy validation and approval.', ['ACT-AST-ROLLBACK'],['POL-AST-ROLLBACK','TASK-AST-ROUTE-APPROVAL'],
 ['What prevents immediate rollback?','Identify evidence needed before an approved action.'],
 [['POL-AST-ROLLBACK','ACT-AST-ROLLBACK'],['TASK-AST-ROUTE-APPROVAL','TASK-AST-ROUTE-POLICY']],
 props=[{'id':'ACT-AST-ROLLBACK','field':'status','equals':'PROPOSED'}])
s('AST-AA-04',A,'Cross-department financial investigation','Trace late carrier confirmations into payout drift.', ['INC-AST-PAYOUT-DRIFT'],['INC-AST-CARRIER-LAG','SYS-AST-PAYOUT','CLM-AST-PAYOUT-EVENT'],
 ['Why do finance payouts disagree with shipment confirmations?'],
 [['INC-AST-PAYOUT-DRIFT','INC-AST-CARRIER-LAG'],['EVD-AST-0013','CLM-AST-PAYOUT-EVENT']])
s('AST-AA-05',A,'Policy-aware export review','Investigate customer export without valid consent.', ['INC-AST-SECURITY-EXPORT'],['POL-AST-PRIVACY','CLM-AST-PRIVACY-EXEMPT'],
 ['Can the customer export proceed without partner consent?'],
 [['POL-AST-PRIVACY','SYS-AST-CUST-ETL'],['EVD-AST-0018','CLM-AST-PRIVACY-EXEMPT']])
s('AST-AA-06',A,'Approval-blocked ownership recovery','Prepare new escalation ownership without inventing approvers.', ['DEC-AST-OWNER-REVIEW'],['INC-AST-PARTNER-SLA','POL-AST-NEW-SLA'],
 ['Show what evidence and human decision are needed to reassign escalation.'],
 [['DEC-AST-OWNER-REVIEW','POL-AST-NEW-SLA'],['EVD-AST-0015','CLM-AST-OWNER-RETIRED']])
s('AST-AM-01',M,'Agent handoff with missing evidence','Detect incomplete evidence_ids in a policy agent handoff.', ['HANDOFF-AST-MISSING'],['TASK-AST-HANDOFF','AGENT-AST-POLICY'],
 ['Why should this handoff be rejected?'],
 [['HANDOFF-AST-MISSING','TASK-AST-HANDOFF'],['HANDOFF-AST-MISSING','AGENT-AST-POLICY']],
 props=[{'id':'HANDOFF-AST-MISSING','field':'status','equals':'INVALID'}])
s('AST-AM-02',M,'Pause, checkpoint and resume','Inspect checkpoint ancestry for an interrupted analyst.', ['EXEC-AST-ROUTE-PAUSED'],['CHECK-AST-ROUTE-1','WB-AST-REVIEW'],
 ['What can the agent safely resume from, and what remains unresolved?'],
 [['EXEC-AST-ROUTE-PAUSED','CHECK-AST-ROUTE-1','EVD-AST-0001'],['EXEC-AST-ROUTE-PAUSED','WB-AST-REVIEW']],
 props=[{'id':'EXEC-AST-ROUTE-PAUSED','field':'status','equals':'PAUSED'}])
s('AST-AM-03',M,'Stale memory vs new trace evidence','Flag old CPU hypothesis when newer trace evidence contradicts it.', ['FIND-AST-CPU-MEMORY'],['FIND-AST-SCHEMA','EVD-AST-0005'],
 ['Which agent memory is stale and why should it not be promoted?'],
 [['FIND-AST-SCHEMA','FIND-AST-CPU-MEMORY'],['FIND-AST-SCHEMA','EVD-AST-0005']],
 props=[{'id':'FIND-AST-CPU-MEMORY','field':'memory_state','equals':'STALE'}])
s('AST-AM-04',M,'Two-agent deadlock','Detect two tasks blocked on each other.', ['TASK-AST-DEADLOCK-A'],['TASK-AST-DEADLOCK-B','AGENT-AST-POLICY'],
 ['Identify a blocking cycle and suggest escalation without executing actions.'],
 [['TASK-AST-DEADLOCK-A','TASK-AST-DEADLOCK-B'],['TASK-AST-DEADLOCK-B','TASK-AST-DEADLOCK-A']])
s('AST-AM-05',M,'Action retry and idempotency','Show why a simulated failed action cannot be retried blindly.', ['ACT-AST-ROLLBACK'],['ATT-AST-RETRY-1','LOCK-AST-ROLLBACK'],
 ['What approval or lock conditions must be checked before retrying rollback?'],
 [['ACT-AST-ROLLBACK','ATT-AST-RETRY-1'],['LOCK-AST-ROLLBACK','SYS-AST-ROUTE-API']],
 props=[{'id':'ATT-AST-RETRY-1','field':'status','equals':'FAILED'}])
s('AST-AM-06',M,'Compaction with provenance','Preserve source citations across agent memory compaction.', ['CMP-AST-ROUTE'],['CHECK-AST-ROUTE-1','EVD-AST-0001'],
 ['Explain why memory compaction must retain links to original evidence.'],
 [['EXEC-AST-ROUTE-PAUSED','CMP-AST-ROUTE','CHECK-AST-ROUTE-1']],
 props=[{'id':'CMP-AST-ROUTE','field':'status','equals':'PENDING_REVIEW'}])
s('AST-AM-07',M,'Validated handoff','Contrast valid and invalid agent handoff contracts.', ['HANDOFF-AST-VALID'],['HANDOFF-AST-MISSING','EVD-AST-0003'],
 ['Compare validated and incomplete handoffs with evidence references.'],
 [['HANDOFF-AST-VALID','EVD-AST-0003']],
 props=[{'id':'HANDOFF-AST-VALID','field':'status','equals':'VALID'}])

s('AST-CB-09',S,'Ambiguous identity reconciliation','Compare two contact candidates without merging the wrong person.', ['SRCREC-AST-IDENTITY'],['PERSON-AST-062','PERSON-AST-028'],
 ['Which people could be R. Menon and why is identity unresolved?'],
 [['SRCREC-AST-IDENTITY','PERSON-AST-062'],['SRCREC-AST-IDENTITY','PERSON-AST-028']],
 absent=[['SRCREC-AST-IDENTITY','RESOLVES_TO','PERSON-AST-062'],['SRCREC-AST-IDENTITY','RESOLVES_TO','PERSON-AST-028']])
s('AST-AA-07',A,'Unknown approval question','Show the unresolved questions blocking policy-aware restoration.', ['Q-AST-ROLLBACK-PROOF'],['ACT-AST-ROLLBACK','TASK-AST-ROUTE-POLICY'],
 ['What approval or evidence is still missing for recovery?'],
 [['Q-AST-ROLLBACK-PROOF','INC-AST-ROUTE-OUTAGE'],['Q-AST-ROLLBACK-PROOF','TOOL-AST-POLICIES']])
s('AST-AM-08',M,'Finance checkpoint recovery','Recover a failed investigation using source-linked checkpoint.', ['EXEC-AST-FINANCE-FAILED'],['EXEC-AST-FINANCE-RESUME','CHECK-AST-FINANCE-1'],
 ['Compare the failed run and resumed state; which evidence survives?'],
 [['EXEC-AST-FINANCE-FAILED','CHECK-AST-FINANCE-1','EVD-AST-0013'],['EXEC-AST-FINANCE-RESUME','CHECK-AST-FINANCE-1']],
 props=[{'id':'EXEC-AST-FINANCE-FAILED','field':'status','equals':'FAILED'}])

# Evaluator-only precise outcomes and typed relationship checks. These are never
# stored on canonical graph entities, in public scenario descriptors or via API.
CONTRACT_DETAILS={
 'AST-CB-01':('Dispatch and picking each have a directed two-hop DEPENDS_ON path to Route DB.',[('SYS-AST-DISPATCH','DEPENDS_ON','SYS-AST-ROUTE-API')]),
 'AST-CB-02':('Schema hypothesis has source-backed support while trace evidence specifically refutes CPU-first.',[('EVD-AST-0005','REFUTES','CLM-AST-ROUTE-CPU')]),
 'AST-CB-03':('Legacy Integrations owned the adapter historically but that ownership expired without a current successor.',[('TEAM-LEGACY','OWNS','SYS-AST-OLD-CARRIER')]),
 'AST-CB-04':('Core Services is the current owner and a separately recorded routing expert can be located.',[('TEAM-CORE','OWNS','SYS-AST-ROUTE-API')]),
 'AST-CB-05':('The May rollback decision was approved, based on an old incident, and affected two systems.',[('DEC-AST-MAY-ROLLBACK','AFFECTS','SYS-AST-ROUTE-DB')]),
 'AST-CB-06':('The new escalation policy supersedes the former version and historical governance is expired.',[('POL-AST-NEW-SLA','SUPERSEDES','POL-AST-OLD-SLA')]),
 'AST-CB-07':('Two credit-note projects have overlapping scope and both affect the Billing API.',[('PROJ-AST-BILL-DUP1','COLLABORATES_WITH','PROJ-AST-BILL-DUP2')]),
 'AST-CB-08':('An uncatalogued, low-confidence cross-domain DEPENDS_ON edge points from Operations BI to Ledger.',[('SYS-AST-ANALYTICS','DEPENDS_ON','SYS-AST-LEDGER')]),
 'AST-CB-09':('The HR record has two CANDIDATE_MATCH links and no RESOLVES_TO link.',[('SRCREC-AST-IDENTITY','CANDIDATE_MATCH','PERSON-AST-062')]),
 'AST-AA-01':('Source commits and trace records back the route investigation with accountable provenance.',[('EVD-AST-0001','DERIVED_FROM','SRCREC-AST-0001')]),
 'AST-AA-02':('Carrier and warehouse consumers each connect to Route DB through bounded DEPENDS_ON traversals.',[('SYS-AST-CARRIER-GW','DEPENDS_ON','SYS-AST-ROUTE-API')]),
 'AST-AA-03':('Rollback is merely proposed, requires approval and is governed by SEV-1 rollback policy.',[('POL-AST-ROLLBACK','GOVERNS','ACT-AST-ROLLBACK')]),
 'AST-AA-04':('Payout drift is correlated with carrier lag and DB snapshots support the event-delay hypothesis.',[('EVD-AST-0013','SUPPORTS','CLM-AST-PAYOUT-EVENT')]),
 'AST-AA-05':('Consent policy governs export; audit and policy evidence refute an exemption.',[('EVD-AST-0018','REFUTES','CLM-AST-PRIVACY-EXEMPT')]),
 'AST-AA-06':('Owner-transfer decision remains proposed, traces to retired owner claim and current SLA policy.',[('DEC-AST-OWNER-REVIEW','BASED_ON','POL-AST-NEW-SLA')]),
 'AST-AA-07':('The approval verification question remains open and requires the policy lookup tool.',[('Q-AST-ROLLBACK-PROOF','REQUIRES','TOOL-AST-POLICIES')]),
 'AST-AM-01':('Invalid handoff is linked to the waiting task and missing evidence_ids must be identified.',[('HANDOFF-AST-MISSING','HANDOFF_FOR','TASK-AST-HANDOFF')]),
 'AST-AM-02':('Paused execution retains a checkpoint based on the original Git and log evidence.',[('EXEC-AST-ROUTE-PAUSED','HAS_CHECKPOINT','CHECK-AST-ROUTE-1')]),
 'AST-AM-03':('New proposed schema finding contradicts stale CPU memory and links to trace evidence.',[('FIND-AST-SCHEMA','CONTRADICTS','FIND-AST-CPU-MEMORY')]),
 'AST-AM-04':('Two blocked tasks form a genuine directed BLOCKED_BY cycle.',[('TASK-AST-DEADLOCK-B','BLOCKED_BY','TASK-AST-DEADLOCK-A')]),
 'AST-AM-05':('Rollback attempt failed; governed action is still proposed and lock state needs checking.',[('ACT-AST-ROLLBACK','HAS_ATTEMPT','ATT-AST-RETRY-1')]),
 'AST-AM-06':('Memory compaction is pending, and its chain reaches a checkpoint preserving evidence references.',[('CMP-AST-ROUTE','BASED_ON','CHECK-AST-ROUTE-1')]),
 'AST-AM-07':('Valid handoff retains an evidence reference while the other handoff lacks evidence_ids.',[('HANDOFF-AST-VALID','BASED_ON','EVD-AST-0003')]),
 'AST-AM-08':('Finance failed execution and paused resumed execution both reference the same saved checkpoint.',[('EXEC-AST-FINANCE-RESUME','HAS_CHECKPOINT','CHECK-AST-FINANCE-1')]),
}
assert set(CONTRACT_DETAILS)==set(p.truth)
for _sid,(_expected,_typed_edges) in CONTRACT_DETAILS.items():
 p.truth[_sid]['expected_outcome']=_expected
 p.truth[_sid]['required_typed_edges']=[{'source':a,'type':b,'target':c} for a,b,c in _typed_edges]
 p.truth[_sid]['success_criteria']['required_typed_edges']=len(_typed_edges)

if __name__=='__main__':
 print(json.dumps(p.save(),indent=2))
