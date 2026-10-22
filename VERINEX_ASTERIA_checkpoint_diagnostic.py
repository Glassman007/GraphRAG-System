"""Read-only Asteria Workspace/Supervisor checkpoint diagnostic.

Run from G:\\graphhacks with the existing Python environment:
  python .\\VERINEX_ASTERIA_checkpoint_diagnostic.py

No model calls, no state changes, and no searches outside the Asteria graph and
its corresponding agent-memory graph. This is a diagnostic, not a repair tool.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

GRAPH = "asteria_company_brain_v1"
TENANT = "asteria"


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Asteria checkpoint audit")
    parser.add_argument("--run-id", help="Inspect one known SRUN ID (optional)")
    parser.add_argument("--limit", type=int, default=12, help="How many recent Asteria runs to inspect")
    args = parser.parse_args()

    from backend.app.config import Settings
    from backend.app.graph.client import FalkorGraphClient
    from backend.app.agent_runtime.memory_store import GraphMemoryStore
    from backend.app.agent_runtime.supervisor_store import GraphSupervisorStore
    from backend.app.agent_runtime.workspace import WorkspaceStore
    from backend.app.services.phase3_utils import node_dict

    settings = Settings.from_env().model_copy(update={"tenant_id": TENANT, "falkordb_graph": GRAPH})
    client = FalkorGraphClient(settings)
    if client.settings.tenant_id != TENANT or client.settings.falkordb_graph != GRAPH:
        raise RuntimeError("Asteria scope mismatch; abort")
    memory = GraphMemoryStore(client)
    workspace = WorkspaceStore(client)
    supervisor = GraphSupervisorStore(client)

    if args.run_id:
        results = memory.graph.ro_query('''
            MATCH (w:AgentWorkspaceRun {tenant_id:$tenant,id:$id}) RETURN w LIMIT 1
        ''', {"tenant": TENANT, "id": args.run_id}).result_set
    else:
        results = memory.graph.ro_query('''
            MATCH (w:AgentWorkspaceRun {tenant_id:$tenant})
            RETURN w ORDER BY w.created_at DESC LIMIT $limit
        ''', {"tenant": TENANT, "limit": min(max(args.limit, 1), 30)}).result_set

    print(f"Asteria checkpoint audit: tenant={TENANT}, graph={GRAPH}")
    print(f"Workspace records inspected: {len(results)}")
    for row in results:
        raw = node_dict(row[0]) or {}
        try:
            record = json.loads(raw.get("document_json") or "{}")
        except (TypeError, ValueError):
            print("[INVALID] Workspace record has malformed document JSON")
            continue
        run_id = str(record.get("id") or "")
        if record.get("graph_id") != GRAPH or record.get("tenant") != TENANT:
            print(f"[SKIP] {run_id or 'unknown'}: not explicitly bound to Asteria")
            continue
        owner = str(record.get("owner") or "")
        if not owner or not run_id:
            print("[INVALID] Asteria record lacks a run ID or owner")
            continue
        try:
            saved = supervisor.get(run_id) or {}
            cp = memory.load_checkpoint(run_id, owner=owner)
            cp_meta = memory.graph.ro_query('''
                MATCH (c:AgentWorkflowCheckpoint {tenant_id:$tenant,id:$id})
                RETURN c.owner, c.revision LIMIT 5
            ''', {"tenant": TENANT, "id": run_id}).result_set
            task_rows = saved.get("tasks") or []
            states = dict(Counter(str(t.get("status") or "UNKNOWN") for t in task_rows))
            event_counts = Counter(str(e.get("kind") or "") for e in (saved.get("events") or []))
            failing = [t for t in task_rows if t.get("status") in ("FAILED", "BLOCKED")]
            doc_tasks = cp.get("tasks") or [] if isinstance(cp, dict) else []
            meta_owner_matches = any(str(m[0] or "") == owner for m in cp_meta)
            print("---")
            print(f"RUN {run_id}")
            print(f"  workspace={record.get('status')} supervisor={saved.get('status') or 'ABSENT'}")
            print(f"  supervisor_tasks={len(task_rows)} states={states}")
            print(f"  handoff_accepted_events={event_counts.get('HANDOFF_ACCEPTED', 0)} "
                  f"handoff_consumed_events={event_counts.get('HANDOFF_CONSUMED', 0)}")
            print(f"  checkpoint={'PRESENT' if cp else 'MISSING'} raw_nodes={len(cp_meta)} "
                  f"owner_matches={meta_owner_matches} revision={(cp or {}).get('revision') if cp else None}")
            print(f"  checkpoint_status={(cp or {}).get('status') if cp else None} "
                  f"checkpoint_tasks={len(doc_tasks)}")
            if failing:
                print("  failed_tasks=" + ", ".join(str(t.get("task_id") or t.get("id"))
                      + ":" + str(t.get("error") or "")[:90] for t in failing))
            if saved.get("status") == "NEEDS_REVIEW" and len(task_rows) == 4 and all(
                    t.get("status") == "COMPLETED" for t in task_rows):
                print("  guidance=NO_FAILED_TASKS_TO_RETRY; review evidence gaps instead")
            elif failing and cp and doc_tasks:
                print("  guidance=RETRY_MAY_BE_ELIGIBLE; backend still enforces status/scope")
            elif failing:
                print("  guidance=FAILED_TASKS_BUT_NO_USABLE_CHECKPOINT; retry currently unavailable")
            elif record.get("status") in ("PAUSED", "INTERRUPTED") and cp and doc_tasks:
                print("  guidance=RESUME_MAY_BE_ELIGIBLE; backend still enforces status/scope")
            else:
                print("  guidance=NO_RECOVERY_ACTION_ESTABLISHED")
        except Exception as exc:
            print(f"[ERROR] {run_id}: {type(exc).__name__}: {str(exc)[:140]}")
    print("No Groq calls or graph writes were performed by this script.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
