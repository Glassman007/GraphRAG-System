# VERINEX — Neon Remote GitHub Integration Audit and Codex Requirements

Audit date: 2026-10-21  |  Input: `GraphRAG-System-main (4).zip` (uploaded source snapshot)

**Target repository:** https://github.com/neondatabase/postgres-sample-dbs

**Objective:** Verify whether VERINEX can connect to this **remote public GitHub repository**, fetch its actual SQL-file contents, transform the declared PostgreSQL schema into an **interconnected, provenance-backed FalkorDB Company Brain graph**, and explore relationships. Also separately test the *live PostgreSQL connector* against a database restored from a sample dump, if desired. These are TWO DIFFERENT integrations; success at one must not be presented as success at the other.

## 0. Evidence and limits — do not call this an end-to-end pass

| Check | Actual result in audit environment | Interpretation |
|---|---|---|
| Existing Phase 9 + Phase 13 unit/algorithm tests | **82 PASSED** | Existing logic has working basic unit coverage. |
| Existing Phase 13 API integration tests | **11 SKIPPED** | No FalkorDB runtime/client; cannot use these to support a success claim. |
| Seven new acceptance tests against actual adapter/normalizer classes and fake external responses | **7 FAILED** | Reproduces missing functionality and incorrect live-connector behavior. See attached `test_verinex_neon_acceptance.py`. |
| `git ls-remote https://github.com/neondatabase/postgres-sample-dbs.git HEAD` | DNS failure: `Could not resolve host: github.com` | Network blocked in local sandbox. This does *not* establish a defect in the user's network/credentials. |
| PostgreSQL server / psycopg / FalkorDB server | Unavailable | Database ingestion and graph persistence not experimentally verified here. |
| GitHub public repository and content | Verified through browser/web lookup, not through VERINEX | Repository contains PostgreSQL SQL dumps such as `dvdrental.sql`, `pagila.sql`, `chinook.sql`, `periodic_table.sql`. |

Official Neon repository describes `dvdrental` as **15 tables**, using a `psql`-loadable SQL dump with `COPY ... FROM stdin`. Its raw `dvdrental.sql` defines real FKs including `payment.rental_id -> rental.rental_id`, `rental.inventory_id -> inventory.inventory_id`, and `inventory.film_id -> film.film_id`.

Reference: https://github.com/neondatabase/postgres-sample-dbs and https://raw.githubusercontent.com/neondatabase/postgres-sample-dbs/main/dvdrental.sql

## 1. Verified code-path defects — locations, evidence, and fixes

### F01: Token required for public GitHub repository (confirmed red test 01)

- Code: `backend/app/ingestion/adapters/github.py`, lines 21–34.
- Current behavior: `health_check()` returns false and `fetch()` raises unless a token and organization string exist, even for public repositories.
- Fix: allow explicitly scoped public repositories in **anonymous mode** with unauthenticated, rate-limited GitHub API calls; preserve token/App access for private sources. For anonymous access, report actual endpoint health and rate-limit status. Never imply anonymous access to private repos.
- Test: exact URL `https://github.com/neondatabase/postgres-sample-dbs` works without a PAT when GitHub's public API is accessible and not rate-limited.

### F02: False-positive GitHub connection check (confirmed red test 02)

- Code: `backend/app/ingestion/adapters/github.py:health_check`; `backend/app/ingestion/source_control.py:test_connection` (approximately lines 325–340).
- Current behavior: valid-looking configuration alone makes status `HEALTHY`; endpoint access, token validity, repository permission, and rate limits are not checked. UI then labels authentication/reachability/API access as PASS.
- Fix: perform a bounded real GET to the configured repository endpoint (or organization endpoint for organization scope); classify 200, 401, 403, 404, 429/secondary limits, timeout, and connection errors distinctly. Return honest separate authentication / API reachability / repository-access checks. No ingestion writes during the check. Redact tokens and DSNs from responses and logs.
- Test: unreachable host or invalid credential never produces `HEALTHY`.

### F03: No exact remote repository fetch (confirmed red test 03)

- Code: `backend/app/ingestion/adapters/github.py:fetch`; `backend/app/ingestion/source_control.py:_safe_connection_config`; `frontend/src/pages/sources/AddSourcePage.tsx`.
- Current behavior: only `GET /orgs/{org}/repos`; user cannot specify a single repository URL in the wizard; the `selected` filter applies only to results returned in an organization page.
- Fix: introduce validated, explicit `owner/repo` scope (the given public URL), call `GET /repos/{owner}/{repo}`, then enumerate files at a pinned commit. Continue to support existing organization discovery. Normalize owner/repo case and prevent SSRF, path traversal, unsupported GitHub hosts and redirects to unexpected hosts. Accept both `https://github.com/neondatabase/postgres-sample-dbs` and `neondatabase/postgres-sample-dbs` in supported source configuration.
- Test: exact repository succeeds, with no dependency on whether it appears in the first organization page.

### F04: Filtered pagination incorrectly ends discovery (confirmed red test 04)

- Code: `backend/app/ingestion/adapters/github.py`, lines 37–46.
- Current behavior: `has_more` computed from `len(repos)` **after** filtering by selected repos. A full upstream page without matching repos therefore causes premature termination. Current per-record cursor is `page+1`, so resuming after a partially processed page can also skip remaining items. Varying `per_page=min(limit,100)` between runs can shift page boundaries.
- Fix: base pagination on upstream page / GitHub Link headers; never derive continuation from filtered length. Implement cursor as a stable source position at a fixed page size (or persistent next URL/item offset) with consistent commit/tree snapshots for file scanning. Persist checkpoint only after processed records; ensure crash recovery does not lose rows/files; handle empty filtered pages by continuing within bounded limits.
- Tests: selected repository on a later page, `max_records=1`, restart after partial page, different batch sizes, stable deduplication, sync re-run.

### F05: Repo listing is not repository content (confirmed by live adapter inspection)

- Code: `backend/app/ingestion/adapters/github.py`, lines 43–45.
- Current behavior: emits only `repository` envelopes containing name, full_name, URL, owner, language. It does not download `dvdrental.sql`, list files, read Git trees, or parse SQL. Therefore this adapter by itself cannot discover tables or relationships in the Neon sample dumps.
- Fix: add source record types for `sql_file` and, downstream, `sql_dataset` / `sql_table` / `sql_column` / `sql_foreign_key` (or a clearly documented normalized intermediate form). Scope the INITIAL test to `dvdrental.sql`; additionally verify enumerating `pagila.sql` and `chinook.sql` without fully materializing every dump. Fetch immutable commit SHA + blob SHA + canonical raw path, file contents (or bounded streaming artifact), and provenance. Do not ingest `COPY` data rows by default and do not execute untrusted SQL from GitHub.
- Test: one selected `.sql` file is materialized into a source record/artifact; `dvdrental.sql` content can be inspected and parsed while never executing it.

### F06: SQL-file records and SQL table records are unmapped (confirmed red tests 05, 07)

- Code: `backend/app/ingestion/normalization/github.py`; `backend/app/ingestion/normalization/database.py`.
- Current behavior: GitHub normalizer only recognizes `user`, `repository`, `pull_request`, `commit`. A `sql_file` yields `UNMAPPED_GITHUB_RECORD_TYPE:sql_file`, **zero entities**. Database normalizer only understands synthetic ownership/dependency records where `raw_metadata.system` exists; a real SQL `table` record yields `UNMAPPED_DATABASE_RECORD_TYPE:table`, **zero entities**.
- Fix: explicit schema normalizers for repository / SQL file / logical database / schema / table / column / primary key / foreign key, capturing actual declared FKs rather than fabricating edges. Do not simply turn every table into a `System` software service with invented `DEPENDS_ON` business semantics. Distinguish **schema declared in repository** from **schema observed in a live database**.
- Test: SQL `table` records generate canonical tables; `sql_file` yields repository-to-file relationship; FK DDL produces actual table-to-table FK edges; warnings for unsupported statements are visible and non-destructive.

### F07: DB `health_check` accepts only an env-var NAME (confirmed red test 06)

- Code: `backend/app/ingestion/adapters/database.py`, lines 19–23.
- Current behavior: `settings.dsn_env` truthy makes health `ok=True` even if the environment variable has no value and no PostgreSQL connection exists.
- Fix: resolve actual DSN securely, connect with a short timeout using a dedicated least-privilege role, run `SELECT 1` and a read-only visibility check on the registered source/view. Classify failures, never echo secrets. Keep this as a separate DB integration test; a GitHub `.sql` file itself is **not** a running database.

### F08: Database read-only transaction is not sufficiently enforced (code review: NOT empirically verified)

- Code: `backend/app/ingestion/adapters/database.py`, lines 43–47.
- Concern: code opens `psycopg.connect(..., autocommit=True)` then executes `SET TRANSACTION READ ONLY`, which is intended for a transaction block. Actual query read-only protection may not apply as intended in autocommit mode. This concern must be verified on a real PostgreSQL server, not reported as a confirmed runtime exploit.
- Fix: execute queries in an explicit read-only transaction (`BEGIN READ ONLY` / connection transaction settings) and with a read-only DB role. Validate server-registered SQL SELECT-only at provisioning; reject unsafe SQL, multiple statements and inappropriate parameters; use statement/time/result limits. Add optional `psycopg[binary]` to integration/development requirements or document it. Inspect and test `GRAPH_HACKS_REGISTERED_DATABASE_VIEWS_JSON` mapping and cursor_column behavior.

### F09: Frontend cannot capture repository URL or PostgreSQL DSN source appropriately (code review)

- Code: `frontend/src/pages/sources/AddSourcePage.tsx`.
- Current behavior: GitHub fields are organization, optional API base URL, token and a comma-separated selected list. No first-class repo URL. Database credentials field stores `token`, while the backend DB adapter expects `dsn` or an env DSN; source form has only `registered_view`.
- Fix: expose validated GitHub repository URL + branch/ref and selected files; provide a secure, server-admin DB connection reference or registered DSN environment variable workflow. Never send raw DSN back to browser. Ensure wizard mapping/preview warns when it creates only one isolated entity and zero canonical relations.

### F10: Company Brain does not yet display a general SQL schema graph (code review)

- Code: `frontend/src/pages/CompanyBrainPage.tsx`, `frontend/src/pages/OrganizationPage.tsx`, `frontend/src/pages/EntityPage.tsx`, `frontend/src/components/GraphView.tsx`; `backend/app/api_v1/router.py` entity/graph endpoints.
- Current behavior: Company Brain page is built around processes and organizational analytics; entity page has relation explorer and blast-radius visualization but no explicit repo-centric SQL schema view. Existing discovery UI does not present a GitHub SQL dataset connection graph.
- Fix: add a source-scoped schema exploration panel or source-linked Company Brain graph. Implement bounded backend graph read returning real repository, file, dataset, tables, column/constraint and FK edges. Show provenance and permit navigation from `payment` to `film` via FK path. Preserve existing Company Brain analytics; new schema graph is *not* proof that ownership/bus-factor/expertise data magically exists.

### F11: Existing schema ontology needs explicit relational concepts (code review)

- Code: `backend/app/graph/schema.py` (`NODE_LABELS`, `RELATIONSHIP_TYPES`), `backend/app/ingestion/writer/graph_writer.py`, resolution and retrieval services.
- Fix: add supported labels such as `SqlTable`, `SqlColumn`, `SqlConstraint` and optionally `SqlDatabase`, `SourceFile` (or reuse clearly typed `System` and `Document`). Add semantically precise edges such as `HAS_COLUMN`, `FOREIGN_KEY_TO`, `DEFINES` while retaining existing `CONTAINS`, `NORMALIZED_TO`, `DERIVED_FROM`. Update whitelists, validation, indexes, entity presentation and path filters. Every normalized fact must link to specific source blob/commit/DDL fragment and IngestionRun; no invented business ownership edges. Maintain tenant isolation.

## 2. Codex runbook: execute the tests that could not run here

**Do this before implementing patches.** Work inside the user's checkout, on a feature branch; never force-push. Capture exact command, stdout, stderr, environment prerequisites, and baseline commit SHA. Do not treat skipped integration tests as passes.

### A. Preflight

1. `git status --short; git rev-parse HEAD`; record current commit and dirty files.
2. `python -m pip install -r requirements.txt`; install missing integration-only extras in isolated environment. `python -m pytest -q backend/tests/test_phase9_algorithms.py backend/tests/test_phase13_algorithms.py`.
3. `docker compose up -d` from VERINEX project root; verify FalkorDB `localhost:6379` and API startup. Do NOT reset or delete existing persistent graphs without explicit permission. Use a dedicated test graph and tenant, e.g. `FALKORDB_GRAPH=verinex_neon_acceptance`, `GRAPH_TENANT_ID=neon-acceptance`.
4. `git ls-remote https://github.com/neondatabase/postgres-sample-dbs.git HEAD`; record connectivity. No GitHub token should be required for this public repo except if GitHub rate-limits the client; in that case use a fine-grained token with least privilege.
5. Copy attached `test_verinex_neon_acceptance.py` to `backend/tests/test_verinex_neon_acceptance.py` and run `python -m pytest -q backend/tests/test_verinex_neon_acceptance.py --tb=short`. These tests are intentionally **RED** on the uploaded snapshot; preserve reproduction evidence before changing code.

### B. Live GitHub integration (not a fixture)

1. In Sources > Add Source choose `GitHub`, mode `Live`. Target *exactly* `https://github.com/neondatabase/postgres-sample-dbs`; select default branch and `dvdrental.sql` file scope. Separate test: scope by organization and selected repo later in pagination.
2. `Test connection`: prove actual remote access and show status for public/anonymous, authenticated, invalid token, 404, timeout, 403/rate limit. Ensure this step does **not** insert canonical graph facts.
3. `Preview ingestion`: show records for repository, file, parsed database/schema/tables/FK constraints. Assert preview `canonical_graph_mutated == false`. Assert proposed canonical relationships > 0, not just provenance edges.
4. `Connect & sync` (full) into isolated FalkorDB test graph. Check fetched, normalized, written, quarantined, failed, artifacts, and edge counts. Expect fully explainable actual edges. Do not declare success from `SUCCEEDED` status alone.
5. Check source record -> file blob/commit -> parsed DDL -> table/FK -> graph entity -> ingestion run provenance. Source artifact URLs should navigate to exact GitHub `blob/{commit_sha}/dvdrental.sql` or equivalent immutable source identity.
6. Repeat exact same sync: no duplicate canonical nodes or edges. Change one fixture blob SHA for deterministic mock test: only affected facts/version edges update. Test deletion/tombstones without deleting historical provenance; assert tenant isolation.
7. Inject 401, 403, 404, 429, 500, timeout, truncated Git tree, oversized file, empty folder, invalid SQL, a network cut after a partial page, and a restart. Assert honest failed/partial status, correct cursor and no silent graph corruption.

### C. Canonical schema-grounded graph acceptance

Use only actual constraints declared in `dvdrental.sql` to assert the following directionality:

```
(neondatabase/postgres-sample-dbs :System {system_type:'repository'})
    -[:CONTAINS]-> (dvdrental.sql :Document {document_type:'sql_dump'})
    -[:DEFINES]-> (dvdrental logical dataset/database)
    -[:CONTAINS]-> (public.payment :SqlTable)

(public.payment :SqlTable)-[:FOREIGN_KEY_TO {constraint:'payment_rental_id_fkey'}]->(public.rental :SqlTable)
(public.rental  :SqlTable)-[:FOREIGN_KEY_TO {constraint:'rental_inventory_id_fkey'}]->(public.inventory :SqlTable)
(public.inventory :SqlTable)-[:FOREIGN_KEY_TO {constraint:'inventory_film_id_fkey'}]->(public.film :SqlTable)
```

The ASCII example above expresses semantic relationships. Codex may choose different explicit ontology names if all tests and UI agree, but must not mislabel FKs as organizational service dependencies. The actual SQL dump includes 15 tables; assert count of unique `public.*` SQL-table entities for this particular file is exactly 15. Assert at least the three specified FK edges exist and the payment-to-film path traverses three FKs. Record total FK count from the parsed source; don't invent a threshold or count.

Graph queries should be scoped to the acceptance tenant and returned canonical labels. If using the recommended `FOREIGN_KEY_TO` type, a representative read is:

```cypher
MATCH p=(a:SqlTable {tenant_id:'neon-acceptance', name:'public.payment'})
  -[:FOREIGN_KEY_TO*1..3]->
  (b:SqlTable {tenant_id:'neon-acceptance', name:'public.film'})
RETURN p
```

Confirm the actual properties / naming scheme if implementation uses different stable table identities. Assert the number of paths / their precise vertices, and verify source provenance for **each** FK edge.

**Acceptance rule:** a lone `System` node for `postgres-sample-dbs` and a few SourceRecord/provenance edges is **not** an interconnected *domain graph*. Company Brain must expose table-to-table, file-to-table, and source-to-evidence links.

### D. Optional, independent LIVE PostgreSQL database test

The remote GitHub URL **does not supply a live Neon/PostgreSQL database connection**. For database ingestion, create a disposable, isolated PostgreSQL instance (not the VERINEX metadata DB and not a real production database). Download the `dvdrental.sql` file **from the exact GitHub repository**, load via `psql -f` (the dump contains `COPY FROM stdin`), then give VERINEX a registered least-privilege DSN/view. Example PowerShell/container workflow:

```powershell
# In a clean scratch folder / throwaway Docker environment
# Download verified SQL source; do not run random scripts from repo
Invoke-WebRequest 'https://raw.githubusercontent.com/neondatabase/postgres-sample-dbs/main/dvdrental.sql' -OutFile 'dvdrental.sql'
docker run -d --name verinex-neon-pg -e POSTGRES_USER=verinex_test -e POSTGRES_PASSWORD=local_test_only -e POSTGRES_DB=dvdrental -p 127.0.0.1:55432:5432 postgres:16
docker cp .\dvdrental.sql verinex-neon-pg:/tmp/dvdrental.sql
docker exec verinex-neon-pg psql -v ON_ERROR_STOP=1 -U verinex_test -d dvdrental -f /tmp/dvdrental.sql
```

Wait for `pg_isready` after starting container, **before** calling `docker exec ... psql`. For integration, provision a separate read-only database login; the above superuser is only for disposable DB bootstrapping. Verify the imported tables with `SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';` and assert 15. Configure `GRAPH_HACKS_REGISTERED_DATABASE_VIEWS_JSON` with an approved, parameterized, deterministic keyset SELECT; resolve DSN from a secure server-side source; do not accept arbitrary SQL in public API. Check table/schema metadata separately from row ingestion. Assert a real connect/SELECT-only check, correct cursor advancement, keyset pagination, and no mutations possible using DB role or transaction.

**Critical:** creating a SQL schema graph from GitHub and querying actual rows from a restored DB are different operations. Do not report both complete after only one works. Do not infer that the GitHub SQL dump is deployed on any Neon production server.

### E. API, Company Brain, and UI path to verify

- Sources wizard: repository URL input; source kind/ref/file scope; clear auth/rate limit state; true `Test` and dry-run `Preview`.
- Source detail: display live ingested records, unique file paths, canonical entities, exact source SHAs, mapping version, error/quarantine breakdown, and status of each sync.
- Source/Company Brain graph: click `dvdrental.sql`, expand tables, click `public.payment`, traverse `payment -> rental -> inventory -> film`. Display edge type `FOREIGN_KEY_TO` and constraint name as evidence, not simulated ownership/business risk.
- Entity provenance: source URL+SHA, exact SQL definition/line region if possible, fetched timestamp, mapper version and ingestion run.
- Return from UI to source; nothing disappears because page lacks a general graph explorer.

### F. Security and performance tests

- GitHub allowed host/HTTPS validation, redirects, repository path validation, secret redaction, authentication boundaries, rate limits / retries with bounded backoff, file size/type limits, binary/gzip handling, zip-bomb safety where archives supported.
- Parse dumps as **data**, never execute SQL from GitHub during repository integration. `COPY` row payload must not become millions of graph nodes by default; exclude direct ingestion of huge `employees.sql.gz` during acceptance.
- Deterministic SHA/commit aware IDs, tenant isolation, idempotent retries, tombstone/renamed file handling, no uncontrolled graph growth from re-sync.
- Large raw SQL statements (including procedural functions and string/dollar quoting) must not break statement boundaries. Use a tested PostgreSQL-aware lexer/parser or scoped parser with clear warnings rather than naïve semicolon-splitting. Support `CREATE TABLE` and `ALTER TABLE ... FOREIGN KEY` from actual file.
- Read-only DB connections require least-privilege role and explicit read-only transactions. Display no password/DSN/raw token in logs, UI or test reports.

## 3. File-by-file modification map

| Location | Required work |
|---|---|
| `backend/app/ingestion/adapters/github.py` | Exact repo URL, anonymous public auth, real health, tree/blob/file fetch, safe cursors / rate limiting / checkpointed pagination. |
| `backend/app/ingestion/adapters/http_json.py` | Typed HTTP errors, redirect host validation, timeouts, rate limit headers, retry semantics and test seams. |
| `backend/app/ingestion/models.py` | File/DDL source record types, immutable remote object identity and schema metadata. |
| `backend/app/ingestion/normalization/github.py` | Normalize fetched SQL files and derived relation candidates, preserve SHA/path. |
| `backend/app/ingestion/normalization/database.py` | Support structured schema metadata / table / FK records from live DB. |
| New `backend/app/ingestion/parsers/postgres_dump.py` (or equivalent) | Bounded, safe SQL DDL extraction without executing SQL or importing COPY rows. |
| `backend/app/ingestion/adapters/database.py` | Real connection probe, proper read-only transaction, registered-view cursor correctness, optional schema introspection. |
| `backend/app/ingestion/source_control.py` | Repo/source/ref/scope validation, meaningful health/preview status; registry/mapping. |
| `backend/app/ingestion/registry.py` | Register enhanced adapters and configuration, preserving fixture behavior. |
| `backend/app/ingestion/pipeline.py` | Per-file sync checkpoint, errors/partial state, idempotent re-sync, dry-run and artifact handling. |
| `backend/app/ingestion/writer/graph_writer.py` | Persist actual typed SQL schema facts and traceable FK relations. |
| `backend/app/ingestion/resolution/service.py` | Canonical identities qualified by repository/commit/file and DB/schema/table; avoid accidental merges across DBs. |
| `backend/app/graph/schema.py` | Add SQL ontology labels, edge types and indexes. |
| `backend/app/api_v1/router.py` / API models | Graph browsing/source-scoped paths and clean schema introspection endpoints, without bypassing permissions. |
| `frontend/src/pages/sources/AddSourcePage.tsx` | Repo URL, scope, safe database config and accurate preview. |
| `frontend/src/pages/sources/SourceDetailPage.tsx` | Sync outcomes/lineage and link to derived graph. |
| `frontend/src/pages/CompanyBrainPage.tsx`, `frontend/src/pages/EntityPage.tsx`, `frontend/src/components/GraphView.tsx` | Source-scoped SQL schema graph and expandable FK paths with provenance. |
| `backend/tests/` + `frontend/src/test/` | Unit, mocked remote failures, SQL parsing, API/Falkor integration, UI and E2E cases. |
| `.env.example`, `README.md`, fresh-clone guide | Exact public GitHub quickstart, optional separate PostgreSQL integration, safe secrets and Windows commands. |

## 4. Definition of DONE — ALL mandatory gates

- [ ] Exact specified public URL connects in LIVE mode, is genuinely queried, and does not require a PAT unless rate limits demand it.
- [ ] GitHub connection test fails accurately for failed access; never claims successful API reachability from configuration alone.
- [ ] Preview shows **real** SQL-file / schema / FK records with zero graph mutations.
- [ ] `dvdrental.sql` yields exactly 15 unique canonical SQL-table nodes within its dataset scope, proper repository/file/DB relationships, and the specified payment→rental→inventory→film FK path.
- [ ] Every table/FK edge has source-blob/commit and ingestion-run provenance; no fake facts or ownership.
- [ ] Resync is idempotent; pagination and crash resume cannot skip selected repos/files; deletion and schema changes preserve source evidence.
- [ ] Company Brain renders and navigates the connected schema; a user can inspect `payment` and see the evidence behind `payment_rental_id_fkey`.
- [ ] All seven supplied red acceptance tests pass (update test contracts only with written justification if API changes); baseline test suite and full applicable backend/frontend tests remain green.
- [ ] **Actual** network-backed test logs from GitHub and FalkorDB are attached and integration tests are NOT skipped. If remote network is unavailable, mark the network gate BLOCKED, not PASS.
- [ ] Optional live PostgreSQL DSN/rows gate is reported separately as PASS / FAIL / BLOCKED, and only PASS if a restored DB is actually connected and queried read-only.
- [ ] Final Codex report identifies changed files, before/after results, graph entity/edge counts, sample Cypher, failures fixed, residual limitations, and exact repro steps.

## 5. One copy/paste prompt for Codex

> You are working in the VERINEX GitHub checkout. Read `VERINEX_Neon_Integration_Audit_and_Codex_Requirements.md` end-to-end, then copy/run `test_verinex_neon_acceptance.py` within the repository. Treat the requested task as a falsifiable LIVE GitHub connector-to-FalkorDB-Company-Brain acceptance project, not a mock/demo. Do not claim success based on existing unit tests, SQL dump downloads alone, or a single System node. Start by collecting baseline test and git SHA evidence. Reproduce seven red tests, then implement the audited fixes, including exact public repository URL support, real connection probe, correct pagination, file/blob ingestion and safe DDL parsing, SQL schema normalizers, typed graph ontology, provenance, Company Brain graph exploration, and idempotent sync. Run actual remote test against `https://github.com/neondatabase/postgres-sample-dbs`, scoped to `dvdrental.sql`, with FalkorDB in an isolated test tenant. Prove all 15 tables and the exact payment→rental→inventory→film FK chain; record a Cypher query, source line/commit lineage, and UI path. Implement and test negative cases and preserve existing features. Treat the live PostgreSQL connection test as a distinct optional gate, using a disposable database with a read-only role, and never conflate a GitHub dump with a running database. Do not destroy existing graphs, hardcode credentials, disable tests, fake passing checks, or force push. Finish with detailed evidence, residual issues and all changed files. If network/servers are unavailable, mark tests BLOCKED and report which validations were done with mocks, rather than claiming full success.
