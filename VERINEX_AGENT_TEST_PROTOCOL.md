# VERINEX investigation + planner acceptance test

This test is designed from the available uploaded VERINEX source snapshot and the completed Stages 2–6 reports. Your current local code may have newer API contracts. It makes no code changes and does not execute SQL.

## Fixed scenario

> Investigate the potential impact of changing `public.film.film_id` from integer to UUID. Identify source-backed direct and indirect schema dependencies, acknowledge unknown application-level dependencies, and produce a safe read-only investigation/migration-preparation plan. Do not execute the migration.

## Ground truth (from verified `dvdrental.sql` source constraints)

- Direct incoming FKs: `film_actor.film_id` via `film_actor_film_id_fkey`; `film_category.film_id` via `film_category_film_id_fkey`; `inventory.film_id` via `inventory_film_id_fkey`.
- Indirect downstream graph paths include `rental -> inventory -> film` and `payment -> rental -> inventory -> film`.
- `film.language_id -> language.language_id` is an **outgoing** FK from `film`, not an incoming reference to `film.film_id`.
- Having a graph path does **not** by itself prove an application must change its schema, or that a column must be converted to UUID. The agent must avoid these inferences without supporting evidence.
- Unknown until separately investigated: actual table rows, query usage, ORMs, API consumers, data migration strategy, locks/downtime, rollout and rollback feasibility.

## How to run

1. Copy `verinex_agent_acceptance_runner.py` into `G:\graphhacks` (it is a standalone script and requires only Python standard library).
2. Start your normal VERINEX FastAPI backend and ensure it can query the ingested Company Brain graph for your user/tenant.
3. Run from PowerShell. The script will prompt privately for your existing VERINEX API key, not your GitHub PAT:

```powershell
cd G:\graphhacks
.\.venv\Scripts\python.exe .\verinex_agent_acceptance_runner.py --source-id SRC-4A2E21E067D415A71E
```

This is a read-only API preflight; check that it can retrieve the schema and whether the agent runtime has a configured model provider. The `--source-id` above comes from the source you showed; replace it if that source's ID changed. If `public.film` is not identified, add `--film-id <the real ID displayed in Company Brain>`.

4. If you consent to passing this public sample-schema context to the model provider **and** to creating labeled, persistent test Situation/Plan records in your currently configured tenant graph, run **one** bounded test:

```powershell
.\.venv\Scripts\python.exe .\verinex_agent_acceptance_runner.py --source-id SRC-4A2E21E067D415A71E --run-model --create-test-plan
```

`--run-model` explicitly enables one provider-backed model run (6 steps, 2,800-token budget, 65-second bound). `--create-test-plan` writes evaluation-only Situation, Investigation, Plan, and possibly Task records. It never executes planned tasks or SQL. Do **not** use `--create-test-plan` if the current graph must remain unchanged. If your provider is unconfigured, the model test will be marked BLOCKED. No retry loop is implemented.

5. Read `reports/verinex_agent_evaluation/LOCAL_TEST_RESULTS.json`, and share it here after checking for any private organizational data in the tool trace. The API key is not written. The evidence file may contain graph content and LLM responses, so redact private content before sharing.

## Acceptance criteria

### Investigation PASS

- A persisted run and actual tool trace show that the agent used graph tools, instead of merely reciting known SQL facts.
- It correctly identifies all 3 direct incoming foreign keys and their constraint names, and recognizes the indirect `rental` and `payment` paths.
- The answer distinguishes source-backed facts, uncertain implications, and unknown application dependencies.
- Provenance citations point to evidence actually available in the tool observations. A correct but ungrounded answer is at most PARTIAL.

### Structured planner PASS

- An actual persisted Plan and linked Task records exist, with meaningful prerequisites and evidence requirements.
- Tasks are specific to `film_id`, not an unrelated incident template, and include verification/reversibility/approval before execution.
- When agent assignments are unsupported by graph evidence, tasks must remain unassigned or blocked rather than inventing expertise.
- The persisted dependency graph is valid (no cyclic prerequisites); plan output as prose alone is not a PASS.

### Likely boundary worth detecting

In the uploaded source snapshot the deterministic planner primarily derives tasks from incident-linked Claims, Questions, and Knowledge Gaps. A bare hypothetical Situation plus an independent AgentRun may yield zero tasks, even when the graph contains real `SqlTable` relationships. **Record this as an integration gap, not a defect in graph ingestion, and never fabricate claims just to make tasks appear.**

### Status labels

`PASS` — live observable required behavior; `PARTIAL` — some required behavior missing; `FAIL` — a specific behavior attempted and incorrect; `BLOCKED` — provider/API/permission/network infrastructure prevents execution; `NOT_TESTED` — not attempted.

Test against your *current local code*, not an older ZIP. No synthetic graph, mock tool responses, background work, database migration, or Codex edit is needed for this first evaluation.
