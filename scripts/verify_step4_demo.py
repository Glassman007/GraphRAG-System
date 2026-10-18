"""Non-destructive GraphHacks demo acceptance checks.

Offline mode validates public scenario contracts against withheld evaluator assertions
through the existing offline pack validator. --live performs only GET requests.
No access tokens, URLs containing secrets, source payloads or evidence bodies are logged.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PACK = ROOT / "fixtures/asteria/v1"
MATRIX = ROOT / "docs/step4_acceptance_matrix.json"
SCENARIOS = ROOT / "frontend/src/data/asteriaScenarios.json"


def data():
    return json.loads(SCENARIOS.read_text(encoding="utf-8"))


def offline():
    from scripts.validate_asteria_pack import validate_pack

    result = validate_pack()
    scenarios = data()
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    errors = list(result["errors"])
    ids = [s["scenario_id"] for s in scenarios]
    if len(ids) != len(set(ids)): errors.append("duplicate public scenarios")
    if set(ids) != {x["scenario_id"] for x in matrix["scenarios"]}: errors.append("acceptance matrix doesn't match public scenarios")
    if any("golden" in json.dumps(s).lower() or "evaluation_only" in json.dumps(s).lower() for s in scenarios):
        errors.append("evaluator-only information in public catalog")
    if any(not x["expected_observation"] or not x["pass_criteria"] for x in matrix["scenarios"]):
        errors.append("incomplete acceptance criteria")
    if any(x["live_verification"] != "NOT_TESTED" for x in matrix["scenarios"]):
        errors.append("matrix claims a live pass before a run")
    for file in ["frontend/src/pages/DemoPage.tsx", "frontend/src/demo/LiveTracePanel.tsx", "frontend/src/demo/demoModel.ts", "frontend/src/test/step4Demo.test.tsx", "frontend/e2e/step4-demo.spec.ts"]:
        if not (ROOT / file).exists(): errors.append("missing test or implementation " + file)
    # Evaluate each scenario's structural contract privately; output only categorical results.
    from scripts.validate_asteria_pack import load_data
    from backend.app.graph.temporal import to_epoch_us
    _, batches, fixture_cases, truth = load_data()
    by_id={node['id']:node for batch in batches for node in batch['nodes']}
    by_pair={}
    for batch in batches:
        for edge in batch['edges']:
            by_pair.setdefault((edge['source'],edge['target']),[]).append(edge)
    case_results=[]
    for case in fixture_cases:
        sid=case['scenario_id']; gold=truth[sid]
        checks=[]
        checks.extend(x in by_id for x in case['entry_ids']+case['focus_ids'])
        checks.extend(bool(by_pair.get((source,dest))) for path in gold['paths'] for source,dest in zip(path,path[1:]))
        checks.extend(any(e['type']==item['type'] for e in by_pair.get((item['source'],item['target']),[])) for item in gold.get('required_typed_edges',[]))
        checks.extend(item['id'] in by_id and by_id[item['id']]['properties'].get(item['field'])==item['equals'] for item in gold['properties'])
        checks.extend(not any(e['type']==relation for e in by_pair.get((source,dest),[])) for source,relation,dest in gold['absent_relationships'])
        for item in gold['temporal']:
            matches=[e for e in by_pair.get((item['source'],item['target']),[]) if e['type']==item['type']]
            def active(edge,at):
                valid_from=edge['properties'].get('valid_from'); valid_until=edge['properties'].get('valid_until')
                return (not valid_from or to_epoch_us(valid_from)<=to_epoch_us(at)) and (not valid_until or to_epoch_us(at)<to_epoch_us(valid_until))
            checks.append(any(active(e,item['active_at']) for e in matches))
            checks.append(not any(active(e,item['inactive_at']) for e in matches))
        case_results.append({'scenario_id':sid,'status':'PASS_FIXTURE' if checks and all(checks) else 'FAIL_FIXTURE',
                             'verified_scope':'Existing seeded graph contracts; NOT a live application result'})
    if any(x['status']=='FAIL_FIXTURE' for x in case_results):errors.append('One or more scenario structural contracts failed')
    return {"ok":not errors,"phase":"offline","scenario_count":len(ids),"tracks":result["tracks"],"cases":case_results,"errors":errors,
            "proof":"Fixture graph structure and contract assertions only; UI not executed, no live agent results asserted."}


def request(base, token, tenant, path):
    req = Request(base + path, headers={"Authorization":"Bearer " + token,"X-Tenant-ID":tenant,"Accept":"application/json"}, method="GET")
    try:
        with urlopen(req, timeout=10) as response:
            obj = json.loads(response.read(8_000_000).decode("utf-8"))
            return {"http_status": response.status, "ok":response.status == 200, "body": obj}
    except HTTPError as e:
        return {"http_status":e.code,"ok":False,"error":"HTTP response rejected"}
    except (URLError,TimeoutError,OSError,ValueError) as e:
        return {"http_status":None,"ok":False,"error":type(e).__name__}


def live(base,token,tenant,limit):
    if tenant != "asteria": raise ValueError("Live scenario verification requires explicitly selected tenant 'asteria'.")
    checks=[]
    session=request(base,token,tenant,"/api/v1/session")
    if not session["ok"] or session["body"].get("tenant_id") != tenant:
        return {"ok":False,"mode":"live-read-only","error":"Session is unauthorized or tenant mismatch","session_http":session["http_status"],"checks":[]}
    for s in data()[:limit]:
        root=s["entry_ids"][0]; enc=quote(root,safe="")
        node=request(base,token,tenant,"/api/v1/entities/"+enc)
        neighbors=request(base,token,tenant,"/api/v1/entities/"+enc+"/neighbors?limit=100")
        count=len(neighbors.get("body",{}).get("items",[])) if neighbors["ok"] else None
        checked=[{"resource":"entity","status":node["http_status"]},{"resource":"neighbors","status":neighbors["http_status"]}]
        if root.startswith("INC-"):
            context=request(base,token,tenant,"/api/v1/situations/"+enc+"/context")
            checked.append({"resource":"situation_context","status":context["http_status"]})
        # PASS confirms bounded API reads only. It must not certify an automated agent workflow.
        passed=all(x["status"]==200 for x in checked)
        checks.append({"scenario_id":s["scenario_id"],"root_id":root,"status":"PASS_READS" if passed else "FAIL_READS","relationships_returned":count,"checks":checked,
                       "runtime_agent_workflow":"NOT_VERIFIED", "ground_truth": "NOT_EXPOSED"})
    return {"ok":all(c["status"]=="PASS_READS" for c in checks),"mode":"live-read-only","checked_at":dt.datetime.now(dt.timezone.utc).isoformat(),"tenant":tenant,
            "scope":"API read availability, not scenario reasoning accuracy or autonomous execution", "checks":checks}


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--live",action="store_true",help="Perform read-only checks against running authenticated Asteria API")
    cli.add_argument("--base-url",default="http://127.0.0.1:8000")
    cli.add_argument("--max-scenarios",type=int,default=24)
    cli.add_argument("--report",default="",help="Optional JSON report output path")
    args=cli.parse_args()
    result=offline()
    if result["ok"] and args.live:
        token=os.environ.get("GRAPH_HACKS_TEST_TOKEN","")
        if not token: cli.error("Set GRAPH_HACKS_TEST_TOKEN in your current shell for live verification (never commit it).")
        result={"offline":result,"live":live(args.base_url.rstrip('/'),token,os.environ.get('GRAPH_HACKS_TENANT','asteria'),min(24,max(1,args.max_scenarios)))}
        success=result["offline"]["ok"] and result["live"]["ok"]
    else: success=result["ok"]
    output=json.dumps(result,indent=2)
    print(output)
    if args.report: Path(args.report).write_text(output+"\n",encoding="utf-8")
    return 0 if success else 1

if __name__=="__main__": raise SystemExit(main())
