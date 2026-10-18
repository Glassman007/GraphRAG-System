# Asteria Logistics Group — optional three-track dataset v1

**Step 1 deliverable.** This is a *fictional, fully simulated* logistics and fulfilment enterprise. It is **not** a live GitHub/Jira/Slack integration, and no automation is executed merely by seeding the graph. The original Northstar fixtures and default `company_brain` graph remain unchanged.

## Scope and version guarantees

| Category | Asteria v1 |
|---|---:|
| Nodes | 388 |
| Relationships | 797 |
| Test scenarios | 24 (9 Company Brain, 7 Connected Agents, 8 Agent Memory & Coordination) |
| Departments | 7 |
| Functional teams | 23 |
| Named synthetic people | 70 |
| Systems | 40 |
| Projects | 16 |
| Incidents | 12 |
| Source modalities | 12 |
| Source records | 26 |
| Evidence records | 25 |
| Agent registry examples | 12 |
| Task examples | 24 |

- Tenant: **`asteria`**; independent graph: **`asteria_company_brain_v1`**.
- Versioned source: `fixtures/asteria/v1` (scenario catalog, seed payload, evaluator-only expectations).
- Generated fixtures: `python scripts/build_asteria_pack.py` (deterministic; development only). Never use the builder to edit hand-authored run state.
- New demo source records include commit messages, Jira tickets, Slack-style chat, application logs, traces, time series summaries, policy extracts, HR and CRM snapshots, DB excerpts, and incident postmortems. Every `SourceRecord` points to a simulated `DataSource`; every `Evidence` points to its originating `SourceRecord`.
- Data is deliberately imperfect: contradictory claims, unassigned ownership, historical policy transitions, provisional evidence, an unresolved identity, a two-task deadlock, stale agent memory, blocked actions, simulated retries and checkpoint-resume examples.

### Main connected story

The **Route Schema v3** deployment precedes a routing incident. The investigation links source commits, open Jira work, logs, trace evidence and a conflicting CPU explanation. The graph exposes downstream warehouse, carrier, payout, SLA and demand-forecast impacts; a policy approval remains unresolved. Meanwhile a retired owner blocks carrier escalation, a different consent incident exposes policy drift, and agents have paused, failed and invalid handoff snapshots. **Potential propagation and proposed actions are not recorded as verified causes or actually executed actions.**

### Scenario contracts

Each `fixtures/asteria/v1/scenarios/*.json` contains:
- `scenario_id`, track, title and concrete entry/focus IDs;
- versioned `starting_state` and clear test questions;
- allowed and forbidden *categories* of operation (these are not claims that an action has executed);
- a declaration of which data may be shown to agents.

`fixtures/asteria/v1/ground_truth/evaluation_only.json` contains evaluator-only expected paths, property predicates, deliberately absent relations, temporal assertions, outcome criterion and measurable pass threshold. **The seed scripts never load the golden expectations.** The offline validator and optional local live-verifier are the only readers of that file. For real model/agent quality evaluation, additionally evaluate answer accuracy, authorization and provenance; graph fixture correctness is a necessary prerequisite, not a substitute.

## Windows: first-time setup (safe, non-destructive)

In PowerShell at the project root with Python dependencies installed and your FalkorDB Docker container running:

```powershell
# First validate offline — no connection to FalkorDB
python scripts/seed_asteria.py --check

# Seed only this new isolated graph; won't reset the old graph
python scripts/seed_asteria.py --seed

# Verify the actual database records read-only
python scripts/verify_asteria_live.py
```

**Important:** `--seed` fails if the target graph already contains nodes. If a prior incomplete Asteria seed exists, `--resume` explicitly fills missing nodes while refusing to overwrite existing node state and rejecting foreign/unmarked content:

```powershell
python scripts/seed_asteria.py --resume
```

Do not run `scripts/reset_graph.py`, `scripts/reseed.py`, or `scripts/seed_all.py` while targeting the Asteria graph. The original Northstar seed loaders do **not** include Asteria.

### Start the backend on Asteria

Stop any currently running GraphHacks backend instance on port 8000, then start the backend from the project root in a new terminal:

```powershell
$env:FALKORDB_GRAPH = "asteria_company_brain_v1"
$env:GRAPH_TENANT_ID = "asteria"
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

`test-asteria-admin-token` is provided **only in development**. Built-in test tokens are disabled by `GRAPH_HACKS_ENV=production` or `GRAPH_HACKS_DISABLE_TEST_AUTH=1`. Never use test tokens on a publicly reachable server.

### Start the frontend on Asteria

In another terminal:

```powershell
cd frontend
$env:VITE_API_BASE_URL = ""
$env:VITE_TEST_TOKEN = "test-asteria-admin-token"
$env:VITE_TENANT_ID = "asteria"
npm run dev
```

The browser's previous `graphhacks.phase12.api` local-storage configuration may override these values. Open **API config** in GraphHacks and set: token `test-asteria-admin-token`, tenant `asteria`, base URL blank. Save. **Do not use `test-admin-token` for Asteria**: it authenticates the `northstar` tenant and the API will return a tenant mismatch.

Then test API connectivity (from any PowerShell terminal):

```powershell
curl.exe -i -H "Authorization: Bearer test-asteria-admin-token" -H "X-Tenant-ID: asteria" http://127.0.0.1:8000/api/v1/session
curl.exe -i -H "Authorization: Bearer test-asteria-admin-token" -H "X-Tenant-ID: asteria" "http://127.0.0.1:8000/api/v1/situations?limit=10"
```

To switch back to Northstar: stop the backend, unset the process-specific variables or set `$env:FALKORDB_GRAPH="company_brain"; $env:GRAPH_TENANT_ID="northstar"`, restart FastAPI and select `test-admin-token` / `northstar` in the frontend API config. **No data migration or reset is needed.**

## Run automated tests

```powershell
python scripts/validate_asteria_pack.py
pytest -q backend/tests/test_asteria_pack.py
pytest -m "not integration" -q
```

The standalone live verifier uses the existing FalkorDB connection with the fixed *Asteria* graph/tenant. It does not create, update or delete records. Integration must run on a machine with FalkorDB available; the offline tests do not prove a live FalkorDB write succeeded.

## Selected concrete demonstrations

| Track | Contract | Entry node and question |
|---|---|---|
| Company Brain | `AST-CB-01` | `SYS-AST-ROUTE-DB` — upstream dependencies and blast radius |
| Company Brain | `AST-CB-02` | `INC-AST-ROUTE-OUTAGE` — contradiction plus provenance |
| Company Brain | `AST-CB-03` | `SYS-AST-OLD-CARRIER` — time-bounded ownership |
| Company Brain | `AST-CB-09` | `SRCREC-AST-IDENTITY` — unresolved person matching |
| Connected Agents | `AST-AA-01` | `INC-AST-ROUTE-OUTAGE` — multi-source investigation |
| Connected Agents | `AST-AA-03` | `ACT-AST-ROLLBACK` — approval-gated action proposal |
| Connected Agents | `AST-AA-05` | `INC-AST-SECURITY-EXPORT` — privacy policy review |
| Agent Memory | `AST-AM-01` | `HANDOFF-AST-MISSING` — reject incomplete handoff |
| Agent Memory | `AST-AM-02` | `EXEC-AST-ROUTE-PAUSED` — checkpoint/resume provenance |
| Agent Memory | `AST-AM-03` | `FIND-AST-CPU-MEMORY` — stale/conflicted agent memory |
| Agent Memory | `AST-AM-04` | `TASK-AST-DEADLOCK-A` — deadlock with `TASK-AST-DEADLOCK-B` |
| Agent Memory | `AST-AM-08` | `EXEC-AST-FINANCE-FAILED` — failed/resumed data access |

All 24 scenario definitions are accessible in `fixtures/asteria/v1/scenarios`. The UI discoverability and ID-less navigation enhancements are **Step 2**, not included in this Step 1 dataset delivery.

## Retrieval indexes

The `SourceRecord.content` data is available through the graph, and GraphRAG's existing indexer can index it. To rebuild *derived* BM25/vector retrieval data for this new tenant, with the backend variables above and source dependencies installed:

```powershell
python scripts/rebuild_retrieval_indexes.py
```

That does **not** connect to external GitHub/Jira/Slack services. It only indexes the seeded synthetic local records, under the `asteria` tenant. Do not assume retrieval ranking or model answers are verified until the local integration tests run.

## Architecture notes and limitations

- Graph queries remain tenant-scoped and performed by FastAPI. The frontend never connects directly to FalkorDB.
- Only the new demo token was added to development authentication. Existing Northstar identities and graph-selection defaults are intact.
- Source records represent *fixtures*, not genuine external connector syncs or customer data.
- Historical records and seeded agent snapshots are demonstrations of possible states. They do not prove actual coordination or allow arbitrary mutations; use normal backend APIs to exercise those workflows.
- Dataset contract tests prove graph shape, paths, time intervals, ID uniqueness and source traceability. End-to-end UI, live graph indexing, permissions and model accuracy must be tested in your environment.
