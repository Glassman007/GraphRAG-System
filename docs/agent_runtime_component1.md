# GraphHacks — Component 1: Agent Runtime / Harness

This is the **first** of six planned agentic components. It adds genuine LLM-directed, bounded, *single-agent* investigation to GraphHacks without inventing capabilities or replacing the canonical FalkorDB organizational graph.

## Features 1.1–1.12: implementation and boundaries

| ID | Feature | Implemented mechanics | Limitations |
|---|---|---|---|
| 1.1 | Natural-language goals | Authenticated POST accepts goal + optional scenario starting entity; Demo Lab goal textarea | No agent discovery if the goal and tools cannot find a valid entity |
| 1.2 | Autonomous planning | LLM first emits a structured bounded plan; can submit replan JSON after new observations | Model-generated plans, not guaranteed optimal |
| 1.3 | Model/tool/observation loop | Real OpenAI-compatible chat-completions tool calls, selected independently by model | Synchronous request; bounded at 12 tool-selection turns |
| 1.4 | Graph-aware tool selection | 9 read-only allowlisted tools: find, get, neighbors, paths, blast radius, incident context, history, expertise, related memory | No unrestricted Cypher and **no mutating domain tools** |
| 1.5 | Dynamic context assembly | Starting entity and linked context included; model can retrieve bounded related claims/findings/checkpoints/outcomes with validity and provenance; each tool refreshes the latest tenant snapshot | Retrieval is structured graph-based; full external vector/semantic index integration is not added here |
| 1.6 | Multi-hop reasoning | Bounded path search and reverse `DEPENDS_ON` traversal; directed links returned with records | No claims about semantic correctness beyond returned source data |
| 1.7 | Sourced conclusions | Final JSON must have cited canonical IDs that appeared in the context or tool responses | Valid IDs **do not prove semantic correctness**; verify claims separately |
| 1.8 | Uncertainty / missing evidence | Final answer captures confidence and explicit gaps; conflicting records remain available | The model labels uncertainty; no separate probabilistic validation engine |
| 1.9 | Adaptive replan | Model can issue a new structured plan following a tool observation; invalid tool arguments return errors it can recover from | No asynchronous task scheduling yet |
| 1.10 | Configurable model providers | OpenAI, Groq, and configured OpenAI-compatible local HTTPS/loopback endpoint | Configure an API key/model yourself; live provider behavior not certified in build environment |
| 1.11 | Bounded execution | Limits on steps, calls per turn, runtime seconds, output tokens, accumulated token usage, prompt size, argument schemas, graph paths | Network calls may fail; no distributed cancellation or queue in this component |
| 1.12 | Structured execution traces | Each run/step persisted as tenant-scoped `Entity:AgentRun`, `Entity:AgentStep` and `HAS_AGENT_STEP` links; GET by run ID | Only activity summaries and source IDs, not raw hidden model reasoning or unbounded documents |

This is **not** Component 2 (supervisor/delegation), Component 3 (automatic long-term agent recall), Component 4 (reactive invalidation), Component 5 (external governed action execution), or Component 6 (full real-time workspace). The small Demo Lab launch panel is an acceptance entry point for Component 1.

## Run on Windows (example: Groq)

Back up your existing GraphHacks folder. Extract the ZIP into a **new** folder rather than overwriting the working branch. In the new project's backend PowerShell terminal, activate its virtual environment and set the graph and provider:

```powershell
$env:FALKORDB_GRAPH = 'asteria_company_brain_v1'
$env:GRAPH_TENANT_ID = 'asteria'
$env:GRAPH_HACKS_AGENT_PROVIDER = 'groq'
$env:GRAPH_HACKS_AGENT_MODEL = 'llama-3.3-70b-versatile'
$env:GROQ_API_KEY = 'YOUR_KEY_HERE' # Keep private; do NOT send to ChatGPT or commit!
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Alternatively, use `GRAPH_HACKS_AGENT_PROVIDER=openai` and `OPENAI_API_KEY` (default model `gpt-4.1-mini`), or provider `compatible` with `GRAPH_HACKS_AGENT_BASE_URL=https://.../v1`, `GRAPH_HACKS_AGENT_MODEL` and optionally `GRAPH_HACKS_AGENT_API_KEY`. Custom endpoint configuration is **server-side only**. All remote providers receive selected organizational context only after the caller explicitly consents on a per-run basis.

Start the existing frontend (no new dependencies):

```powershell
cd frontend
npm ci
npm run typecheck
npm test
npm run build
npm run dev
```

Select tenant `asteria`, Asteria development test token (`test-asteria-admin-token`) and the same backend graph. Open `/demo?scenario=AST-AA-01`. Under **Ask the graph-aware agent**, review the prompt, tick the transmission consent box, click **Start autonomous investigation**. It should autonomously plan, select graph tools, inspect observations and return a sourced conclusion, or clearly report an insufficient/failed run. Click linked source IDs to check the claims. `ARUN-*` IDs can be loaded again after restarting the backend because traces live in FalkorDB.

**IMPORTANT**: The run writes `AgentRun` and `AgentStep` *trace nodes* to the currently selected graph, but does not modify existing organizational facts or execute business actions. For strictly non-destructive tests, use a disposable Asteria test graph. The earlier Northstar graph remains untouched when the Asteria graph is selected.

## API contracts

`GET /api/v1/agent-runtime/status` — requires `READ_GRAPH`, returns provider configuration availability (no key), bounded/runtime capability flags.

`POST /api/v1/agent-runtime/runs` — requires `READ_GRAPH`, `READ_EVIDENCE`, `CREATE_INVESTIGATION` and explicit `allow_external_model=true`. Example:

```json
{
  "goal": "Investigate the route dispatch outage and identify affected systems with evidence.",
  "source_entity_id": "INC-AST-ROUTE-OUTAGE",
  "max_steps": 8,
  "max_tokens": 18000,
  "max_seconds": 90,
  "allow_external_model": true
}
```

Response includes `id`, `status` (`COMPLETED`, `INSUFFICIENT_EVIDENCE`, `INCOMPLETE` or `FAILED`), `answer`, `citations`, `knowledge_gaps`, `plan`, `trace`, `steps_executed`, `tokens_used`, and optional `error`.

`GET /api/v1/agent-runtime/runs/{run_id}` — requires `READ_GRAPH` and `READ_EVIDENCE`. Reads tenant-scoped persisted trace.

Errors: 401 unauthenticated, 403 insufficient permissions or tenant mismatch, 422 consent/invalid request, 503 provider unconfigured. Provider failures during a started run return `status=FAILED` and a persisted error trace, without inventing a success.

### Example CLI request

```powershell
curl.exe -s -X POST `
 -H 'Authorization: Bearer test-asteria-admin-token' `
 -H 'X-Tenant-ID: asteria' `
 -H 'Content-Type: application/json' `
 -d '{"goal":"Investigate route dispatch outage and affected systems.","source_entity_id":"INC-AST-ROUTE-OUTAGE","allow_external_model":true}' `
 http://127.0.0.1:8000/api/v1/agent-runtime/runs
```

Do not use those built-in test credentials in production. Organizational data may contain sensitive information; choose an approved model provider and data sharing policy before enabling external transmission.

## Tests and acceptance

- `python -m pytest backend/tests/test_agent_runtime_step1.py -q` — scripted-provider mechanics (not a fake live agent success): goal/plan, dynamically selected tool calls, tool observation return, grounded source-ID checking, replanning, forbidden write tools, model failure trace, authentication, consent, provider config and HTTP entry point.
- `python -m pytest -m "not integration" -q` — original backend regression suite plus new tests.
- `npm run typecheck && npm test && npm run build` — verify frontend locally.
- **Manual live provider test**: ensure the plan and several tool selection steps appear in persisted trace, source IDs open in the tenant graph, final text is grounded in actually returned evidence, and after restart `GET /agent-runtime/runs/{run_id}` returns the same trace.

Limitations of the build environment: the new backend unit tests run with an injected provider; no real Groq/OpenAI requests, actual FalkorDB persistence, local frontend compilation or browser E2E execution were performed here. Treat those as **not verified** until run against your installation.
