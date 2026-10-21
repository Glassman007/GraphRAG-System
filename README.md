> **Asteria v1 (three-track enterprise demonstration):** An optional, isolated synthetic dataset with 24 scenario contracts and a non-destructive seed command is documented in [docs/asteria_dataset_v1.md](docs/asteria_dataset_v1.md). It does not replace or reset the existing Northstar graph.

# GraphHacks — Graph-Native Company Brain

GraphHacks is a **graph-native organizational intelligence system** built around FalkorDB.

It turns fragmented organizational data—incidents, systems, teams, people, claims, evidence, tasks, decisions, policies, documents, telemetry, and historical events—into a temporal, provenance-aware **Company Brain** that can reason about relationships, retrieve supporting evidence, coordinate work, learn from validated outcomes, and expose those capabilities through a stable API and functional frontend.

The core design rule is simple:

> **FalkorDB decides what is connected and where to look. Retrieval, planning, coordination, and UI layers operate on top of that graph instead of replacing it.**

---

## What GraphHacks Can Do

### Graph reasoning
- relational entity resolution;
- conflict-aware claims and evidence;
- authority and contradiction resolution;
- responsibility and expertise routing;
- blast-radius dependency analysis;
- knowledge-gap detection;
- structural precedent discovery;
- decision genealogy;
- graph anomaly detection;
- counterfactual simulation.

### Planning and coordination
- graph-backed Plans and Task DAGs;
- candidate assignee routing;
- task claiming and execution state;
- checkpoints and resume;
- handoffs and branch work;
- blocker/contention/deadlock detection;
- governed actions;
- idempotent action execution.

### Learning and organizational memory
- Evidence → Claim → Decision → Outcome writeback;
- validation and revalidation;
- controlled memory promotion;
- invalidation when supporting knowledge changes;
- historical responsibility/ownership;
- precedent learning;
- expertise evidence.

### Company Brain analytics
- process reconstruction;
- policy-vs-practice drift;
- commitments and obligations;
- ownership gaps;
- initiative collisions;
- bus-factor analysis;
- bottlenecks;
- organizational bridges;
- expertise coverage;
- anomaly/motif deviation.

### Organizational data ingestion
- GitHub;
- Jira;
- Slack;
- Teams adapter contract;
- documents;
- telemetry;
- configured relational database reads;
- configured internal APIs.

All external data passes through:

```text
Source Adapter
    ↓
SourceRecord
    ↓
Normalization
    ↓
Entity Resolution
    ↓
Provenance + Trust
    ↓
Safe Graph Write
    ↓
FalkorDB
```

External text or messages do **not** automatically become organizational truth.

### Graph-first retrieval / GraphRAG
GraphHacks does not perform global vector search first.

```text
Question / Investigation
        ↓
FalkorDB
        ↓
Relevant entities + neighborhood
        ↓
Relevant sources / artifacts / temporal scope
        ↓
Specialized retrieval
        ├── BM25 lexical
        ├── vector
        ├── document / chunk
        ├── metadata
        ├── configured SQL
        └── configured API
        ↓
Retrieved Evidence
        ↓
FalkorDB
```

Retrieved material is written back as provenance-linked **Evidence**, not automatically promoted truth.

---

# Functional Frontend

Phase 12 adds a React operations console that communicates only with the stable Phase 11 `/api/v1/...` boundary.

Implemented views include:

- Situation Dashboard;
- Investigation Graph;
- GraphRAG retrieval workspace;
- Plan / Task DAG;
- Agent coordination / blackboard;
- Claims + Evidence Explorer;
- Conflict / Authority Resolution;
- Decision Genealogy / Replay;
- Action Governance;
- Entity Explorer;
- Blast Radius;
- Counterfactual Simulator;
- Anomalies;
- Company Brain analytics.

The Company Brain UI exposes:

- processes;
- policy drift;
- commitments;
- ownership gaps;
- expertise;
- bus factor;
- bottlenecks;
- bridges;
- duplicate initiatives.

The browser does **not** contain Cypher, direct FalkorDB access, SQL logic, or duplicated backend reasoning.

---

# Architecture

```text
                    ┌─────────────────────────────┐
                    │       React Frontend        │
                    │  Engineering / Ops Console  │
                    └──────────────┬──────────────┘
                                   │
                              /api/v1/...
                                   │
                    ┌──────────────▼──────────────┐
                    │      FastAPI Boundary       │
                    │ Auth • Tenant • Validation  │
                    │ Permissions • Idempotency   │
                    └──────────────┬──────────────┘
                                   │
        ┌──────────────────────────┼───────────────────────────┐
        │                          │                           │
┌───────▼────────┐       ┌─────────▼────────┐        ┌────────▼────────┐
│ Graph Reasoning │       │ Planning / Agents │        │ Graph Retrieval │
│ Phase 3–4       │       │ Phase 5–7        │        │ Phase 10        │
└───────┬────────┘       └─────────┬────────┘        └────────┬────────┘
        │                          │                           │
        └──────────────────────────┼───────────────────────────┘
                                   │
                        ┌──────────▼──────────┐
                        │      FalkorDB       │
                        │ Canonical Company   │
                        │ Brain + Provenance  │
                        └──────────┬──────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │ Phase 9 Ingestion +         │
                    │ Artifact / Retrieval Indexes│
                    └─────────────────────────────┘
```

FalkorDB remains the canonical organizational store. Lexical/vector indexes are derived and rebuildable.

---

# Tech Stack

## Backend
- Python 3.12+
- FastAPI
- Pydantic
- FalkorDB
- pytest
- httpx

## Frontend
- React 18
- TypeScript
- Vite
- React Router
- TanStack Query
- Cytoscape.js
- Vitest
- React Testing Library
- Playwright

## Infrastructure
- Docker Compose
- FalkorDB
- local content-addressed ArtifactStore
- deterministic BM25 / local retrieval indexes

---

# Repository Structure

```text
graphhacks/
├── backend/
│   ├── app/
│   │   ├── api_v1/          # Stable external API
│   │   ├── graph/           # FalkorDB schema/client/query utilities
│   │   ├── ingestion/       # Phase 9 source ingestion
│   │   ├── retrieval/       # Phase 10 GraphRAG/retrieval
│   │   └── services/        # Reasoning, planning, coordination, analytics
│   └── tests/
│
├── frontend/
│   ├── src/
│   │   ├── api/             # Centralized typed API modules
│   │   ├── auth/
│   │   ├── components/
│   │   ├── graph/
│   │   └── pages/
│   └── e2e/
│
├── scripts/
│   ├── apply_schema.py
│   ├── reseed.py
│   ├── rebuild_retrieval_indexes.py
│   ├── verify_phase9_ingestion.py
│   ├── verify_phase10_browser.py
│   ├── verify_phase11_api.py
│   └── verify_phase12_ui.py
│
├── docs/
├── docker-compose.yml
├── requirements.txt
└── .env.example
```

---

# Quick Start

## 1. Clone the repository

```bash
git clone <your-repository-url>
cd graphhacks
```

---

## 2. Start FalkorDB

Docker is the easiest option:

```bash
docker compose up -d
```

FalkorDB is exposed on:

```text
localhost:6379
```

The FalkorDB browser is exposed by the container on:

```text
http://localhost:3000
```

> The frontend also uses port `3000`, so normally use the FalkorDB browser only when the frontend dev server is stopped, or change one of the port mappings locally.

---

## 3. Create the backend environment

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
pip install -r requirements.txt

Copy-Item .env.example .env
```

### macOS / Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env
```

Default development configuration:

```env
FALKORDB_HOST=localhost
FALKORDB_PORT=6379
FALKORDB_GRAPH=company_brain
FALKORDB_PASSWORD=
GRAPH_TENANT_ID=northstar
```

---

## 4. Initialize the graph

For a clean local demo:

```bash
python scripts/validate_fixtures.py
python scripts/reseed.py
```

For an existing GraphHacks graph that only needs current schema additions:

```bash
python scripts/apply_schema.py
```

---

## 5. Run the backend

```bash
uvicorn backend.app.main:app --env-file .env --reload --host 127.0.0.1 --port 8000
```

Useful URLs:

```text
API:      http://127.0.0.1:8000
Swagger:  http://127.0.0.1:8000/docs
Health:   http://127.0.0.1:8000/health
Ready:    http://127.0.0.1:8000/api/v1/ready
```

---

# Run the Frontend

```bash
cd frontend
```

Create the frontend environment file:

### Windows

```powershell
Copy-Item .env.example .env
```

### macOS / Linux

```bash
cp .env.example .env
```

Default development values:

```env
VITE_API_BASE_URL=
VITE_TEST_TOKEN=test-admin-token
VITE_TENANT_ID=northstar
```

The Vite dev server proxies `/api` to the backend running on port `8000`.

Install and run:

```bash
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

---

# Local Authentication

Development mode includes deterministic test principals such as:

```text
test-admin-token
test-reader-token
```

The frontend sends:

```text
Authorization: Bearer <token>
X-Tenant-ID: <tenant>
X-Request-ID: <generated-id>
```

Test credentials are disabled automatically when:

```env
GRAPH_HACKS_ENV=production
```

They can also be disabled explicitly with:

```env
GRAPH_HACKS_DISABLE_TEST_AUTH=1
```

Do not commit production credentials.

---

# External API

Phase 11 exposes a stable API under:

```text
/api/v1/...
```

Major resource groups include:

```text
/api/v1/situations
/api/v1/investigations
/api/v1/entities
/api/v1/paths
/api/v1/claims
/api/v1/evidence
/api/v1/plans
/api/v1/tasks
/api/v1/agents
/api/v1/decisions
/api/v1/actions
/api/v1/simulations
/api/v1/history
/api/v1/processes
/api/v1/risks
/api/v1/anomalies
/api/v1/company-brain
/api/v1/retrieval
/api/v1/session
```

The API enforces:

- authentication;
- tenant isolation;
- permissions;
- query bounds;
- temporal `as_of` semantics;
- request correlation;
- standardized errors;
- idempotency for relevant mutations;
- action governance.

There is no unrestricted Cypher, SQL, filesystem, or arbitrary URL endpoint.

---

# GraphRAG / Retrieval Indexes

Rebuild the derived retrieval indexes with:

```bash
python scripts/rebuild_retrieval_indexes.py
```

The lexical/vector indexes are not canonical knowledge stores. They can be rebuilt from FalkorDB provenance plus source/artifact material.

---

# Testing

## Backend

Run everything:

```bash
pytest -v
```

Run only deterministic/non-FalkorDB tests:

```bash
pytest -m "not integration" -v
```

The Phase 12 repository contains **685 backend tests**.

Real integration tests require a running FalkorDB instance.

---

## Frontend

```bash
cd frontend

npm test
npm run typecheck
npm run build
```

The repository contains:

- 134 Vitest cases;
- 2 Playwright browser tests.

---

# End-to-End Acceptance

The repository includes isolated verification runners.

## Phase 9 — ingestion

```bash
python scripts/verify_phase9_ingestion.py
```

## Phase 10 — graph-first retrieval

```bash
python scripts/verify_phase10_browser.py
```

## Phase 11 — external API

```bash
python scripts/verify_phase11_api.py
```

## Phase 12 — live frontend

Install Playwright Chromium once:

```bash
cd frontend
npx playwright install chromium
cd ..
```

Then run:

```bash
python scripts/verify_phase12_ui.py
```

The Phase 12 runner:

1. creates an isolated FalkorDB graph;
2. seeds deterministic Northstar data;
3. starts the real FastAPI backend;
4. starts the Vite frontend;
5. executes the Playwright browser flow;
6. verifies that frontend output changes when backend graph state changes;
7. leaves `company_brain` untouched.

---

# Core Demo Story

The default Northstar fixture demonstrates a complete organizational reasoning workflow:

```text
Situation / Incident
        ↓
Investigation
        ↓
Graph Scope
        ↓
GraphRAG Retrieval
        ↓
Evidence
        ↓
Claim + Conflict
        ↓
Authority Resolution
        ↓
Plan
        ↓
Task Graph
        ↓
Agent Coordination
        ↓
Decision Genealogy
        ↓
Governed Action
        ↓
Blast Radius
        ↓
Counterfactual Simulation
        ↓
Company Brain Analytics
        ↓
Anomalies
```

---

# Important Design Guarantees

### FalkorDB stays canonical
Vector or lexical indexes never replace the organizational graph.

### Provenance is preserved
Facts, Evidence, SourceRecords, Artifacts, retrievals, decisions, and actions retain lineage.

### Retrieval is graph-first
The system resolves organizational scope before searching detailed text.

### Retrieved text is not truth
Retrieved material becomes Evidence and must still pass existing validation/promotion rules.

### Historical queries are explicit
Temporal reads use backend `as_of` semantics rather than filtering current data in the frontend.

### Actions remain governed
API or frontend clients cannot bypass approval, evidence, authority, locking, or idempotency rules.

### Frontend logic stays thin
The browser requests, renders, inspects, and operates. It does not reproduce graph reasoning.

---

# Documentation

Useful starting points:

```text
docs/external_api.md
docs/api_authentication.md
docs/graphrag_architecture.md
docs/graph_first_retrieval.md
docs/ingestion_architecture.md
docs/learning_loop.md
docs/coordination_model.md
docs/frontend_architecture.md
docs/frontend_backend_mapping.md
docs/ui_routes.md
docs/ui_permissions.md
docs/ui_acceptance.md
docs/capability_status.md
```

For the latest Phase 12 implementation and verification notes, see:

```text
docs/phase12_completion_report.md
```

---

# Current Verification Status

The repository contains the complete Phase 1–12 implementation.

Environment-independent backend tests and source validation were executed during development. Full verification of FalkorDB-backed integration tests and the live Playwright browser flow requires a local environment with:

- FalkorDB running;
- frontend npm dependencies installed;
- Playwright Chromium installed.

Run:

```bash
pytest -v
```

and:

```bash
python scripts/verify_phase12_ui.py
```

before treating a fresh clone/environment as fully verified.

---

# Security Notes

Do not commit:

- `.env`;
- provider tokens;
- database credentials;
- production API principals;
- local ArtifactStore data;
- retrieval indexes;
- virtual environments;
- `node_modules`.

Use the supplied `.gitignore` and `.env.example` files.

---

# License

No license is included by default.

If you intend to make the repository publicly reusable, add an explicit license such as MIT, Apache-2.0, or another license appropriate for your project.

## VERINEX merged agent stack (Components 1–6)

This repository integrates Component 1's improved Groq/OpenAI-compatible model provider (including token pacing, bounded observations, evidence grounding, request deduplication and rate-limit handling) with Components 2–6 below. The model settings are illustrated in `.env.example`; **no actual API key is bundled**. Copy the example to a private `.env`, set `GROQ_API_KEY` privately and launch with `uvicorn ... --env-file .env` so those settings are loaded. Do not expose `.env` through the frontend.

Start with `python -m pytest -q -m "not integration"`; see `MERGE_REPORT.md` for the tested scope, unresolved live checks and safe follow-up commands. An actual FalkorDB instance, Node dependencies and Groq access are needed for complete end-to-end validation.

## Component 2 — Supervisor & Task Scheduler

The Demo & Scenario Explorer now includes an optional **Component 2 / Supervisor & Task Scheduler** panel below the existing single-agent runtime. It decomposes organizational investigations, schedules read-only specialists in parallel when their prerequisites permit, passes evidence-checked handoffs, persists supervisor task and event state in FalkorDB, and flags conflicting/high-risk conclusions for human review. Incident records use a deterministic dependency/evidence/verification/remediation-proposal DAG; other objectives use schema-validated model-generated plans.

Use `GET /api/v1/agent-runtime/supervisor/registry` to inspect specialist tools, `POST /api/v1/agent-runtime/supervisor/runs` to start a consented run, and `GET /api/v1/agent-runtime/supervisor/runs/{id}` to reopen it. Requires the existing provider setup plus authenticated graph/evidence/investigation permissions. No specialist can execute external business actions; remediation is a proposal only. See [Component 2 implementation, demo and limitations](docs/component2_supervisor_scheduler.md).

### Component 3 — Persistent Agent Memory (verified cross-session knowledge)

The supervisor now stores private agent discoveries and owner-scoped workflow checkpoints in a **separate tenant-scoped FalkorDB memory graph**, promotes only corroborated graph-checkable assertions, and injects current verified knowledge into later specialist runs. The Demo & Scenario Explorer includes a searchable memory/provenance panel, validity reviews, and a run-resume action. Model statements are not blindly treated as facts; completed tasks are reused on restart, but interrupted in-flight read-only tool calls may repeat. See [`docs/component3_persistent_agent_memory.md`](docs/component3_persistent_agent_memory.md) for supported predicates, HTTP APIs, acceptance tests, and production caveats.

### Component 4 — Reactive Organizational Learning

Confirmed ingested changes propagate through a persisted event inbox to verified agent memory and affected supervisor plans. Re-verification is targeted, and further LLM work requires fresh consent. See [`docs/component4_reactive_organizational_learning.md`](docs/component4_reactive_organizational_learning.md).

### Component 5 — Governed Tool Execution (disabled externally by default)

The Demo & Scenario Explorer includes a **Governed Tool Execution** panel. Evidence-grounded proposals are stored in a separate tenant-scoped action ledger, checked against authoritative policies and read-only blast-radius simulation, and require an independent authenticated human approver before a configured HTTPS adapter can dispatch a real external action. Tool execution uses a durable CAS claim and a stable operation key; ambiguous failures never trigger automatic replays. A remote acknowledgment is not completion: the trusted adapter must independently confirm success or failure through an authenticated GET readback. Failed/uncertain actions can be escalated, and verified outcomes are made available to the Component 4 learning store.

Nothing in this repository enables an external action connector until its explicit environment URL and secret are set. Do **not** use a live deployment receiver without validating its idempotency/authorization implementation. See [`docs/component5_governed_tool_execution.md`](docs/component5_governed_tool_execution.md).

## Component 6 — Live Agent Workspace

Go to **`/agent-workspace`** for a unified read-only multi-agent investigation UI. It launches real, explicitly authorized bounded supervisor work, displays graph-persisted specialist activity, supports cooperative pause/cancel and checkpoint resume, inspects verified agent memory, provides graph evidence links, and embeds independently governed action approvals. Scenarios are starting inputs, not computed results.

See [Component 6 deployment and API guide](docs/component6_live_agent_workspace.md) for the single-worker deployment requirement, test instructions and remaining production limitations.

