# VERINEX Neon integration baseline (Stage 1)

Date: 2026-10-21 (Asia/Calcutta). This is an inspection baseline, not an integration pass. No production code was changed, and no full suite, live ingestion, graph write, or PostgreSQL restore was run.

## Repository state

- Project root and execution directory: `G:\graphhacks` (`git rev-parse --show-toplevel` and `Get-Location`).
- HEAD: `065aadd407c2cd9d8653c0baf635d9955c93b18c`.
- Initial `git status --short --untracked-files=all`: **123 tracked deletions, 16 tracked modifications, 49 untracked files**. The modifications include `.env.example`, `README.md`, `backend/app/ingestion/pipeline.py`, `backend/app/api_v1/router.py`, other application/tests/frontend files, and the three supplied Neon audit/test/log files are untracked. The detailed initial status was observed before testing. All pre-existing files and modifications were preserved. This report is the sole intentional new file.
- The audit describes an uploaded ZIP snapshot; findings below were checked against this checkout at the HEAD and dirty working tree above. In particular, `pipeline.py` and `router.py` have pre-existing modifications.

## Relevant implementation inspected

| File(s) | Current responsibility and finding |
| --- | --- |
| `backend/app/ingestion/adapters/github.py`, `adapters/http_json.py` | Live GitHub adapter checks only token/org/base URL configuration; fetch lists `/orgs/{org}/repos`, emits repository metadata only, filters after fetching, and derives `has_more` from the filtered count. HTTP helper can issue JSON GETs, but no file/tree/blob fetch is used. |
| `backend/app/ingestion/adapters/database.py` | Fixture or registered row ingestion. Live health checks whether a row provider, DSN credential, or `dsn_env` *name* exists; it does not connect. Live fetch requires optional `psycopg`, a DSN, fixed query, and cursor column. It uses `autocommit=True` followed by `SET TRANSACTION READ ONLY`; actual transaction protection was not exercised against PostgreSQL. |
| `backend/app/ingestion/registry.py`, `normalization/mappings.py`, `normalization/github.py`, `normalization/database.py` | Register adapters/normalizers and fixture sources. GitHub maps user/repository/PR/commit; database maps service ownership/dependency rows. Neither maps SQL files or table/schema records. Repository maps to `System` with `system_type=software_service`. |
| `backend/app/ingestion/source_control.py`, `backend/app/api_v1/router.py` | Source configuration, allowlisted connector base URL, registered database view, test/preview/sync, source/lineage and general entity/path APIs. GitHub scope is a selected list, with no validated exact repository URL/file/ref contract. `test_connection` turns adapter's configuration-only `ok` into `HEALTHY` and four apparent PASS checks. Preview is a dry run, but cannot propose SQL schema facts that are never fetched/mapped. |
| `backend/app/ingestion/pipeline.py`, `provenance/service.py`, `artifacts/local.py` | Bounded sync, normalization, cursor checkpoint, dry run, source record/run provenance, content-addressed local artifacts. Pipeline stops on an empty page; this compounds selected-repo pagination failure. Current GitHub record cursor is `page+1` for every record, so a partial page can skip remaining repos on resume. |
| `backend/app/ingestion/resolution/service.py`, `writer/graph_writer.py`, `backend/app/graph/schema.py` | Canonical resolution, provenance-linked node/edge upserts, ontology validation/indexes. These are reusable, but schema lacks SQL table/column/FK types. Current canonical IDs can fall back to name alone, insufficient to distinguish same-named tables across datasets. Writer adds source record/run properties to canonical edges and links records to entities. SQL constraint provenance is not present because SQL is not parsed. |
| `frontend/src/pages/sources/AddSourcePage.tsx`, `SourceDetailPage.tsx`, `frontend/src/pages/CompanyBrainPage.tsx`, `EntityPage.tsx`, `frontend/src/components/GraphView.tsx` | Existing source wizard, status/history, Company Brain analytics and general entity graph. Wizard asks for org/token/selected list or registered DB view, not exact GitHub repository/file/ref. Company Brain currently has process/risk views; no repository-scoped SQL schema exploration. Entity page can show generic relations/lineage. |
| `backend/tests/test_phase9_algorithms.py`, `test_phase13_algorithms.py`, `test_phase9_api_integration.py`, `test_phase13_api_integration.py`, `backend/tests/conftest.py`, `test_verinex_neon_acceptance.py` | Existing fixture/connector contracts and API integration coverage; supplied tests specify seven desired Neon behaviors using mocked external responses. API integration tests were inspected but not executed because Stage 1 requested relevant connector unit tests, not a live graph suite. |

## Executed checks and exact results

All commands below ran from `G:\graphhacks` in PowerShell. Commands were read-only except pytest's ordinary local cache effects; no tracked file was edited.

| Command | Result |
| --- | --- |
| `Get-Location; git rev-parse --show-toplevel; git rev-parse HEAD; git status --short --untracked-files=all` | Root and HEAD above; initial dirty tree recorded. |
| `python -m pytest -q test_verinex_neon_acceptance.py --tb=short` | **7 failed**, 0 passed, in 1.48 s; exit 1. Failure IDs 01–07 match supplied log. |
| `python -m pytest -q backend/tests/test_phase9_algorithms.py backend/tests/test_phase13_algorithms.py -k 'adapter or github or database or connector or source_registry or credential' --tb=short` | **40 passed, 42 deselected**, in 1.24 s; exit 0. These are fixture/algorithm tests, not live service tests. |
| `git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=5 ls-remote https://github.com/neondatabase/postgres-sample-dbs.git HEAD` | Succeeded; remote HEAD `b54cb67534bf20775803b181b7a1c6f573422161`. Network access to GitHub works in this environment. This does not exercise VERINEX or fetch `dvdrental.sql`. |
| `python -c "import importlib.util; print('falkordb:', bool(importlib.util.find_spec('falkordb'))); print('psycopg:', bool(importlib.util.find_spec('psycopg')))"` | Printed `falkordb: False`, `psycopg: True`. The FalkorDB Python client is absent in this interpreter, so graph integration tests cannot run as configured without installing it. |
| `docker info --format '{{.ServerVersion}}'`; `Test-NetConnection -ComputerName localhost -Port 6379 -InformationLevel Quiet`; `docker ps --format '{{.Names}} {{.Ports}}'` | Docker server `29.8.2`; port check `True`; `falkordb-dev` exposes 6379. No graph query or integration test was performed. |

The prior audit's `82 PASSED`, `11 SKIPPED`, and DNS failure were observations from a different environment, not reproduced results here. The current acceptance failures do reproduce. Live GitHub-to-FalkorDB, SQL table/FK counts, UI navigation, idempotent resync, and live PostgreSQL read-only behavior remain **unverified**, not passed.

## Acceptance failures: classification and root causes

| Test | Observed failure and classification |
| --- | --- |
| 01 public without token | **Confirmed implementation gap:** GitHub health returns false without token even for public repo scope. **Test limitation:** assertion only asks for `ok`, and its mock never proves a remote request; a config-only success would pass the test without meeting live acceptance. |
| 02 unreachable host | **Confirmed defect:** GitHub health returns true from config and never invokes mocked HTTP client; `test_connection` can incorrectly report HEALTHY/PASS for reachability and API access. |
| 03 exact repo endpoint | **Confirmed missing capability, with contract assumption:** adapter calls org listing, never `/repos/{owner}/{repo}`. Test treats `scope_config.selected=[owner/repo]` as an exact-repo request, though the current public contract only describes it as a filter over org results. Stage 2 should define that contract explicitly. |
| 04 selected later page | **Confirmed defect:** `has_more` uses the filtered list length, losing a full upstream page with no match. Per-record `page+1` cursor and variable `per_page` pose related resume risks by code inspection; those specific scenarios were not separately tested. |
| 05 SQL file normalization | **Confirmed missing capability:** `sql_file` produces zero entities and `UNMAPPED_GITHUB_RECORD_TYPE:sql_file`. The adapter also never emits such a record, so the test exercises a desired future input rather than current ingestion. |
| 06 DB health | **Confirmed defect:** an unset env var name makes health `ok=True`; no DSN resolution or database probe occurs. The test does not validate a successful live connection. |
| 07 SQL table normalization | **Confirmed missing capability:** `table` produces zero entities and `UNMAPPED_DATABASE_RECORD_TYPE:table`. Present DB adapter is a registered-row reader, not a schema introspector; test uses a proposed future record shape. |

Additional inspected concerns: `autocommit=True` with `SET TRANSACTION READ ONLY` needs a live PostgreSQL verification before calling it a runtime security failure. Exact SQL dump contents, 15-table count, FK path and immutable blob provenance were not independently verified in Stage 1; the current adapter has no path to produce them. Existing `requirements.txt` lists FalkorDB but not `psycopg`; `psycopg` happens to be available locally. The audit's claim that PostgreSQL/FalkorDB are unavailable does not describe this workstation's Docker/port state, but service behavior has not been tested.

## Reusable pieces and Stage 2 dependencies

- Reuse `SourceConfig`, `SourceRecordEnvelope`, `ArtifactPayload`/`SOURCE_FILE`, `ConfiguredJsonHttpClient` (with bounded access rules), source registry, dry-run pipeline, cursor/run bookkeeping, `LocalArtifactStore`, provenance `SourceRecord`/`IngestionRun` version links, resolution/writer upserts, tenant-scoped graph client, and existing source/entity/path/lineage APIs and `GraphView`.
- External requirements: reachable GitHub public API/raw content endpoints and rate-limit handling; an immutable commit/blob identifier for `dvdrental.sql`; a bounded SQL DDL parser that reads schema and constraints without executing dump SQL or `COPY` data; `FalkorDB==1.8.0` client and isolated graph/tenant for integration; optional separate PostgreSQL with `psycopg`, restored dump, registered query/view and least-privilege role. Docker and a FalkorDB port are present here, but actual graph readiness remains to be checked.
- Avoid conflating GitHub-hosted SQL schema ingestion with connection to a running PostgreSQL database. Do not assume a repository listing, successful sync status, or provenance edges alone prove a connected domain graph.

## Recommended specific Stage 2 scope

1. Define validated GitHub `owner/repo`, ref and selected file scope (starting with `dvdrental.sql`) through source configuration/API/UI; preserve organization discovery. Make anonymous public API access and bounded real connection checks report truthful auth, reachability, permissions and rate limits.
2. Fetch exact repository metadata and a pinned commit's SQL file/blob content with stable pagination and crash-safe cursors; enforce host/path/size limits and retain source SHA, URI and artifact provenance.
3. Parse only schema DDL (no execution or row ingestion); normalize repository, file, logical dataset/schema, tables, columns, keys and declared foreign keys. Add explicit SQL ontology/edge types and dataset-qualified canonical identities. Preserve source record, blob/commit and run evidence for each fact.
4. Extend writer and bounded source-scoped graph read/UI to navigate actual table FK paths and evidence. Verify dry-run has zero canonical writes, idempotent resync, deletion/version behavior, tenant isolation, and the specified `payment → rental → inventory → film` path against a real pinned dump.
5. Treat live PostgreSQL connector work as an independent integration track: resolve/probe DSN, enforce an explicit read-only transaction and registered query/view policy, then test against a disposable restored database. First update/clarify the seven acceptance contracts where they currently only test mock behavior.
