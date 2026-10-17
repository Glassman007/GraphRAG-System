                "passed": sum(1 for x in self.results if x["ok"]),
                "failed": sum(1 for x in self.results if not x["ok"]),
            },
            "ids": self.ids,
            "results": self.results,
        }
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

        q = self.ids
        cypher_path = ROOT / f"phase6_8_browser_queries_{self.graph_name}.cypher"
        cypher = f"""// Select graph in FalkorDB Browser: {self.graph_name}
// These queries inspect objects created by scripts/verify_phases_6_8.py.

// PHASE 6 — task ownership, execution, checkpoints, findings, handoff
MATCH (t:Entity:Task {{id:'{q.get('investigation_task','')}'}})
OPTIONAL MATCH (t)-[:CLAIMED_BY]->(a:Entity:Agent)
OPTIONAL MATCH (t)-[:HAS_EXECUTION]->(e:Entity:Execution)
OPTIONAL MATCH (e)-[:HAS_CHECKPOINT]->(cp:Entity:Checkpoint)
RETURN t, a, e, cp;

MATCH (f:Entity:Finding {{id:'{q.get('finding','')}'}})
OPTIONAL MATCH (f)-[r]-(x)
RETURN f, r, x;

MATCH (h:Entity:Handoff {{id:'{q.get('handoff','')}'}})
OPTIONAL MATCH (h)-[r]-(x)
RETURN h, r, x;

MATCH (b:Entity:WorkBranch)
WHERE b.id IN ['{q.get('branch_merged','')}','{q.get('branch_rejected','')}']
OPTIONAL MATCH (b)-[r]-(x)
RETURN b, r, x;

MATCH (a:Entity:Action {{id:'{q.get('action','')}'}})
OPTIONAL MATCH (a)-[:HAS_ATTEMPT]->(attempt:Entity:ActionAttempt)
OPTIONAL MATCH (a)-[r]-(x)
RETURN a, attempt, r, x;

// PHASE 7 — promotion and learning lineage
MATCH (f:Entity:Finding {{id:'{q.get('finding','')}'}})-[:PROMOTED_TO]->(c:Entity:Claim {{id:'{q.get('promoted_claim','')}'}})
OPTIONAL MATCH (e:Entity:Evidence)-[:SUPPORTS]->(c)
OPTIONAL MATCH (d:Entity:Decision)-[:BASED_ON]->(c)
OPTIONAL MATCH (t:Entity:Task)-[:ADDRESSES]->(c)
RETURN f, c, e, d, t;

MATCH (s:Entity:System {{id:'{q.get('ownership_system','')}'}})
OPTIONAL MATCH (owner:Entity)-[r:OWNS]->(s)
RETURN owner.id, owner.name, r.valid_from, r.valid_until, s.id;

// PHASE 8 — process semantics
MATCH (a:Entity:Event)-[r:TRIGGERED|BEFORE]->(b:Entity:Event)
WHERE a.tenant_id='northstar'
RETURN a.id, type(r), b.id, a.occurred_at, b.occurred_at
ORDER BY a.occurred_at;

// Policy requirements
MATCH (p:Entity:Policy {{id:'POL-DB-04'}})-[r:REQUIRES]->(x)
RETURN p, r, x;

// Commitment COM-017
MATCH (c:Entity:Commitment {{id:'COM-017'}})-[r]->(x)
RETURN c, r, x;

// Duplicate-work source graph
MATCH (p:Entity:Project)-[r]->(x)
WHERE p.id IN ['PROJ-REFUND-A','PROJ-REFUND-B','PROJ-REFUND-C']
RETURN p, r, x;

// Bus factor source relationship
MATCH p=(person:Entity:Person {{id:'PERSON-ISHA'}})-[:EXPERT_IN]->(s:Entity:System {{id:'SYS-LEDGER-EXPORT'}})
RETURN p;

// Collaboration bridge fixture
MATCH p=(a)-[r]-(b)
WHERE a.id IN ['PERSON-DEV','TEAM-SECURITY','TEAM-PLATFORM','PROJ-RELEASE-GATE']
   OR b.id IN ['PERSON-DEV','TEAM-SECURITY','TEAM-PLATFORM','PROJ-RELEASE-GATE']
RETURN p;
"""
        cypher_path.write_text(cypher, encoding="utf-8")
        return report_path, cypher_path


def main() -> int:
    runner = Runner(ARGS.graph)
    print("=" * 78)
    print("GraphHacks Phase 6-8 LIVE acceptance runner")
    print(f"Repository : {ROOT}")
    print(f"FalkorDB   : {os.environ['FALKORDB_HOST']}:{os.environ['FALKORDB_PORT']}")
    print(f"Test graph : {ARGS.graph}")
    print("NOTE: company_brain is NOT modified; this runner uses an isolated graph.")
    print("=" * 78)

    exit_code = 0
    error_text = None
    try:
        runner.setup()
        runner.phase6()
        runner.phase7()
        runner.phase8()
    except Exception as exc:
        exit_code = 1
        error_text = f"{type(exc).__name__}: {exc}"
        print("\n[ABORTED] A critical acceptance check failed.")
        print(error_text)
        traceback.print_exc()
    finally:
        try:
            report_path, cypher_path = runner.write_artifacts()
            passed = sum(1 for x in runner.results if x["ok"])
            failed = sum(1 for x in runner.results if not x["ok"])
            print("\n" + "=" * 78)
            print(f"RESULT: {passed} passed, {failed} failed")
            if error_text:
                print(f"Critical error: {error_text}")
            print(f"JSON report  : {report_path}")
            print(f"Browser Cypher: {cypher_path}")
            print(f"FalkorDB graph: {ARGS.graph}")
            if ARGS.cleanup and exit_code == 0:
                runner._delete_graph_if_present()
                print("Temporary acceptance graph deleted (--cleanup).")
            else:
                print("Temporary graph kept so you can inspect it at http://localhost:3000")
                print(f"Select graph: {ARGS.graph}")
            print("=" * 78)
        except Exception as artifact_exc:
            print(f"Could not write acceptance artifacts: {artifact_exc}")
            exit_code = 1
