# Stage 5 integration result

**Full remote workflow: BLOCKED.** A new public GitHub source registered through `POST /api/v1/sources` with no credential, the pinned commit, and `dvdrental.sql` selected. Its single live connection test returned `RATE_LIMITED` (GitHub HTTP 403), so no remote ingestion was attempted. This is not a remote end-to-end pass. Evidence: `STAGE_5_RUN.json` (graph `verinex_neon_stage5_2ded2df6`, tenant `neon-stage5-2ded2df6`). No personal access token was required or supplied.

**Downstream workflow: PASS with the integrity-checked local Stage 3 artifact and an in-process GitHub transport stand-in.** The file's SHA-256 and Git blob SHA matched Stage 3 evidence before use. A separately registered source in a new graph completed two full syncs through the normal Sources API. Both runs reported `SUCCEEDED`, with 2 fetched, 2 normalized, 2 written, zero failed/quarantined and one stored artifact. The source's own ingestion state was `SUCCESS`. Both reads showed **15 SqlTable, 86 SqlColumn, 33 SqlConstraint, and 18 source-defined FOREIGN_KEY_TO** facts; a direct FalkorDB read after both runs confirmed those counts and 2 completed IngestionRun nodes. No SQL dump chunks were produced. Evidence: `STAGE_5_DOWNSTREAM.json` (graph `verinex_neon_stage5_downstream_c3b8a163`, tenant `neon-stage5-c3b8a163`). This separate check does not establish live GitHub availability.

## Confirmed boundaries and fixes

| Boundary | Failure and repair |
| --- | --- |
| New graph → Sources registration | `GraphSnapshot.load()` used a read-only query before FalkorDB had created the graph key, raising `Invalid graph operation on empty key`. `SourceControlService.create_source()` now initializes the configured graph before its first snapshot. A fresh-graph API regression passes. |
| Add Source → GitHub configuration | The existing form sent only an organization filter; users could not submit a direct repository, pinned ref, or selected file. Its GitHub live fields now send repository/ref and `scope_config.files`, with `anonymous=true` when no token is entered. The existing organization flow remains available. Source edits preserve the selected-file scope. |
| Sources sync → completion | The normal API indexed the entire 2.76 MB SQL dump as retrieval prose after persisting the schema graph. One isolated local attempt remained `RUNNING` for several minutes while creating over 1,700 retrieval chunks, so it was stopped. The pipeline now skips retrieval chunking only for `sql_file` artifacts; the raw artifact and parsed graph facts remain stored. The fresh downstream run finished twice in about ten seconds total and exposed a genuine `SUCCESS` source state. The stopped attempt's separate test graph was left intact and is not used as pass evidence. |

## Files modified

`backend/app/ingestion/source_control.py`, `backend/app/ingestion/pipeline.py`, `frontend/src/pages/sources/AddSourcePage.tsx`, `frontend/src/pages/sources/SourceDetailPage.tsx`; focused tests in `backend/tests/test_neon_workflow_stage5.py`, `frontend/src/test/neonSourceStage5.test.tsx`, `frontend/e2e/neon-workflow-stage5.spec.ts`; local downstream verifier `scripts/verify_neon_stage5_downstream.py`; evidence files `STAGE_5_RUN.json` and `STAGE_5_DOWNSTREAM.json`; this report. No GitHub retrieval, SQL parser, graph schema, Company Brain graph component, or unrelated agent code was changed. No Git reset, clean, restore, commit, or push was performed.

## Focused verification

| Exact command | Result |
| --- | --- |
| `G:\gitTools\.venv-verinex-stage3\Scripts\python.exe -m pytest -q backend/tests/test_neon_workflow_stage5.py backend/tests/test_neon_schema_stage4.py --tb=short` | **3 passed**. Fresh graph registration, focused API sync with small SQL and no dump chunking, SQL graph access controls. Installed TestClient deprecation warning only. |
| `npm test -- src/test/neonSourceStage5.test.tsx src/test/sqlSchemaStage4.test.tsx` (from `frontend`) | **4 passed**. Verified public repo/ref/file payload without a token, file scope retained on source edit, and existing SQL graph UI behavior. |
| `npm run typecheck` (from `frontend`) | **PASS**. |
| `G:\gitTools\.venv-verinex-stage3\Scripts\python.exe -m scripts.verify_neon_stage5_downstream` | **PASS**, local transport only. Two normal API syncs and unchanged 15-table/18-FK counts. |
| `npx playwright test e2e/neon-workflow-stage5.spec.ts --reporter=line` (from `frontend`, with the isolated source ID set) | **1 passed** against the newly registered downstream graph. |
| `git diff --check -- backend/app/ingestion/source_control.py backend/app/ingestion/pipeline.py frontend/src/pages/sources/AddSourcePage.tsx frontend/src/pages/sources/SourceDetailPage.tsx` | **PASS**, line-ending notices only. |

The browser opened the normal Sources page, found the newly registered source, used its **Explore this source in Company Brain** link, displayed the graph from the API's configured isolated graph and tenant, inspected a GitHub link at the actual `payment_rental_id_fkey` SQL line, and navigated **payment → rental → inventory → film** through recorded FK controls. No browser graph-name switch or production graph-name hardcoding was used. The local API and Vite processes were stopped after verification.

**Remaining blocker:** GitHub anonymous rate limiting prevented the required live connection and remote sync in this stage. The remote check needs a later single retry after the reported reset; the downstream pass must remain labeled separately. No repeat remote requests were made after the 403.
