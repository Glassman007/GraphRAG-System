# GraphHacks Step 2 — UX / UI integration guide

## Scope

Step 2 is built **on top of Asteria Step 1**. It retains the merged Matrix / Read the Rain visual design, the Northstar fixtures, the Asteria v1 fixture, the governed backend, auth checks, and existing graph structure.

This is a complete source ZIP, not a patch. Neither this release nor its setup needs `reseed.py`.

## New backend read endpoints

- `GET /api/v1/situations?q=...&status=...&limit=...&cursor=...` — tenant-scoped incident list, server-side substring search against incident ID, name, title, summary, description and directly connected Team/System/Project descriptions or names. Filtering happens before pagination.
- `GET /api/v1/situations/statuses` — distinct statuses of visible incident records in the tenant graph.
- `GET /api/v1/entities/browse?kind=System&q=...&limit=...&cursor=...` — tenant-scoped paginated discovery, with kind allowlist; `Department` maps to Teams with `team_type=DEPARTMENT`.

These endpoints require `READ_GRAPH` and do not offer arbitrary Cypher queries, tenant overrides, or mutations.

## Frontend changes

- `/situations`: real status dropdown, debounced text search, meaningful empty and loading states; page is not replaced by a loading screen every keystroke.
- `/situations/:id`: incident summary, readable timeline/evidence/tasks, connected systems, cross-links to Company Brain/Work/Simulations and an editable investigation goal.
- All GraphView usages (including the landing page): interactive category legend, search/focus, zoom, fit, three layouts, contextual node/edge detail, explicit recorded vs inferred distinctions, and bounded neighboring graph expansion through the existing API.
- `/organization`: searchable/paginated graph organization browser, with category selection and descriptive labels.
- `/scenarios`: all 24 Asteria scenario titles, questions, entry IDs and allowed operations, with no evaluator-only ground truth. Links are only enabled in the Asteria tenant.
- `/simulations`: supported backend intervention modes (`remove_dependency`, `rollback_change`, `add_compatibility_layer`, `bus_factor`), guided preview, guarded run, result comparison and explicit path graphs. Incident roots now resolve to *explicitly affected systems* when generating counterfactual blast radius.
- Reusable searchable ID picker is used in core workflows for Work, Agents, Plan creation, Company Brain, simulations, claim/evidence, action governance, investigations, and path selection.
- ReadableRecord replaces several raw JSON views; opt-in technical details remain available. API errors distinguish authentication, authorization, missing data and dependency outages.

### Important limits

- Frontend does **not** fabricate dependency edges, path tracing, an inferred relationship, or a graph traversal. Edges in simulation previews come only from backend-returned `paths[].edges`.
- Graph node expansion is bounded by the existing `/entities/{id}/neighbors` `limit=50`. The newly added expanded nodes are client-side visibility only.
- Asteria scenarios are seeded fixture contracts, **not** proof that all multi-agent operations were executed live.
- A status dropdown reports currently present statuses, not speculative states.
- Frontend entity pickers keep manual ID entry for advanced users.
- Step 3 agent/work functional expansion is not included here.

## Windows run procedure

1. Back up your existing GraphHacks working directory and keep your current `.env` files outside the new ZIP. Do not commit or upload any secrets.
2. Extract `GraphHacks_Step2_UI_Complete.zip` into a separate directory. Recreate the same local `.env` values from your existing deployment, using Asteria values from `docs/asteria_dataset_v1.md` if Asteria is your current tenant.
3. Start your existing FalkorDB container (`docker compose up -d`). **Do not reset or reseed your existing graph.**
4. From the extracted project, activate your backend virtual environment, ensure `pip install -r requirements.txt` has been done and run:

   ```powershell
   uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
   ```
5. In a second PowerShell window:

   ```powershell
   cd frontend
   npm ci
   npm run typecheck
   npm test
   npm run build
   npm run dev
   ```

6. Open the frontend Vite URL, and open **API config**. Verify that its tenant and token match the running backend. Previously saved browser settings can override `.env`.
7. Confirm `/api/v1/session`, `/api/v1/situations/statuses`, `/api/v1/entities/browse?kind=System` return 200 with your authenticated headers.

## Acceptance checklist

1. **Situations status:** selecting All, Open or Resolved produces the appropriate result set; typing in the search bar does not remount the whole page; matching a related system returns connected incidents even on later pages.
2. **Situation details:** inspect a real Asteria incident, claims, timeline and affected systems. IDs remain available but are secondary.
3. **Interactive graph:** hide/show Evidence nodes on landing and a situation; search by node ID; focus and expand a selected node; click a relationship; switch layouts.
4. **Organization:** browse Teams/Departments, People, Systems and Projects; verify real graph data rather than static placeholder cards.
5. **Scenarios:** catalog displays 24 cases for Asteria across the three tracks, while evaluator answers are excluded. Northstar mode does not link to non-existent Asteria entries.
6. **Simulations:** pick a real incident / system, actual connected dependency endpoints and run remove_dependency; compare backend before/after. Results with zero removed edges are valid and must not claim an impact.
7. **Work:** use a searchable situation to create a plan, select a real agent for a task, inspect readable coordination details. Work engine functional upgrades are Step 3.
8. **Permissions:** without organizational analytics permission, simulation execution must be disabled; with expired auth, the UI must distinguish 401 from 403.
9. Run backend tests with `pytest -m 'not integration' -q`. Run real FalkorDB-backed integration and browser acceptance tests locally.

## Verification in the creation sandbox

- Asteria fixture validator: PASS.
- Backend non-integration regression: 429 passed, 299 integration-marked deselected.
- TSX syntax parsing: PASS. Full TS typecheck, Vitest, Vite build and browser E2E are **not verified** in this sandbox because npm dependencies could not be installed. Execute those commands locally before merging/deploying.
