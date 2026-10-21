# Stage 3: Neon SQL schema into Company Brain and FalkorDB

Date: 2026-10-21 (Asia/Calcutta). Starting and current commit: `a93cfe21cd8dbc0fffa51e58bff487f3ef1fdacd`. No commit or push was made. Pre-existing working-tree changes were preserved.

**Result:** The real Stage 2 `SOURCE_FILE` artifact for `neondatabase/postgres-sample-dbs/dvdrental.sql` flowed through the existing ingestion pipeline into a disposable FalkorDB graph. Two full ingestions succeeded with zero quarantined or failed records. The graph has 15 distinct tables, 86 columns, 15 primary keys, and 18 source-defined foreign keys. Counts of schema entities and edges were unchanged after the second ingestion. FalkorDB Cypher returned the requested `payment → rental → inventory → film` path.

## Files changed

| File | Stage 3 change |
| --- | --- |
| `backend/app/ingestion/normalization/postgres_schema.py` | New PostgreSQL-aware pg_dump table extractor using `pglast`; isolates CREATE TABLE and ALTER TABLE declarations, skips COPY streams, validates PK/FK references, and never executes SQL. |
| `backend/app/ingestion/normalization/github.py` | Validates the actual SQL `SOURCE_FILE` bytes, SHA-256, Git blob SHA, path and immutable commit URL; converts extracted schema to repository, file, table, column and constraint candidates plus graph relations. This replaces `sql_file` quarantine for valid artifacts. |
| `backend/app/graph/schema.py` | Adds `SqlTable`, `SqlColumn`, `SqlConstraint` labels and `DEFINES`, `HAS_COLUMN`, `HAS_CONSTRAINT`, `FOREIGN_KEY_TO` relations. |
| `backend/app/ingestion/resolution/service.py` | Uses exact repository/file-qualified IDs for parsed schema entities. |
| `backend/app/ingestion/writer/graph_writer.py` | Reuses the existing writer with stable edge IDs, including the source constraint identity for parallel FKs, and stable artifact lineage. |
| `backend/app/ingestion/provenance/service.py` | Uses stable source-to-data-source and source-to-artifact lineage edge IDs on repeat ingestion. |
| `requirements.txt` | Adds `pglast==8.7`. |
| `backend/tests/test_neon_sql_stage3.py` | Focused extraction, normalization, integrity and COPY boundary tests. |
| `scripts/verify_neon_sql_stage3.py` | Fetches the pinned public GitHub artifact, ingests it twice through `IngestionPipeline`, and queries a disposable FalkorDB graph. |
| `reports/verinex_neon_integration/STAGE_3_REMOTE.json` | Successful live run evidence: source identity, counts, actual FKs, and Cypher path. Contains no SQL data or credentials. |
| `reports/verinex_neon_integration/STAGE_3_RESULTS.md` | This report. |

The Stage 2 GitHub connector and frontend were not modified. No remote SQL was run. `pglast` parses only isolated table declarations; this is intentionally scoped to the table DDL patterns in this pg_dump, not arbitrary PostgreSQL programs or changed-commit synchronization. The existing pipeline, registry, resolver, provenance service, artifact store and graph writer remain the integration path. IDs include repository, file path and schema object; source metadata and FK edges carry repository, path, commit, blob, file hash, immutable URL, constraint name, columns, and source DDL location.

## Actual schema extracted and stored

Pinned commit: `b54cb67534bf20775803b181b7a1c6f573422161`; source path: `dvdrental.sql`; Git blob: `5fe9c6fee0ba073362952964edd04a6527c24aee`; SHA-256: `fa73f75e117e7f2af010ba7542b224d76897a17ac4972be257513c86ad4da12a`.

Tables: `public.actor`, `public.address`, `public.category`, `public.city`, `public.country`, `public.customer`, `public.film`, `public.film_actor`, `public.film_category`, `public.inventory`, `public.language`, `public.payment`, `public.rental`, `public.staff`, `public.store`.

All 18 foreign keys below were read from the file's ALTER TABLE constraints and matched against FalkorDB edges; none were inferred from names:

| From table.column | Constraint | To table.column |
| --- | --- | --- |
| `address.city_id` | `fk_address_city` | `city.city_id` |
| `city.country_id` | `fk_city` | `country.country_id` |
| `customer.address_id` | `customer_address_id_fkey` | `address.address_id` |
| `film.language_id` | `film_language_id_fkey` | `language.language_id` |
| `film_actor.actor_id` | `film_actor_actor_id_fkey` | `actor.actor_id` |
| `film_actor.film_id` | `film_actor_film_id_fkey` | `film.film_id` |
| `film_category.category_id` | `film_category_category_id_fkey` | `category.category_id` |
| `film_category.film_id` | `film_category_film_id_fkey` | `film.film_id` |
| `inventory.film_id` | `inventory_film_id_fkey` | `film.film_id` |
| `payment.customer_id` | `payment_customer_id_fkey` | `customer.customer_id` |
| `payment.rental_id` | `payment_rental_id_fkey` | `rental.rental_id` |
| `payment.staff_id` | `payment_staff_id_fkey` | `staff.staff_id` |
| `rental.customer_id` | `rental_customer_id_fkey` | `customer.customer_id` |
| `rental.inventory_id` | `rental_inventory_id_fkey` | `inventory.inventory_id` |
| `rental.staff_id` | `rental_staff_id_key` | `staff.staff_id` |
| `staff.address_id` | `staff_address_id_fkey` | `address.address_id` |
| `store.address_id` | `store_address_id_fkey` | `address.address_id` |
| `store.manager_staff_id` | `store_manager_staff_id_fkey` | `staff.staff_id` |

All table names in this table use the `public` schema. Extraction reported zero warnings.

## Exact checks and results

Commands ran from `G:\graphhacks` using the isolated `G:\gitTools\.venv-verinex-stage3` environment with `pglast==8.7` and `FalkorDB==1.8.0`. No full repository suite ran.

| Exact command | Result |
| --- | --- |
| `G:\gitTools\.venv-verinex-stage3\Scripts\python.exe -m pytest -q backend/tests/test_neon_sql_stage3.py backend/tests/test_github_connector_stage2.py -k 'stage3 or stage2' --tb=short` | **68 passed** in 2.69 s: 4 Stage 3 tests and 64 Stage 2 connector regressions. |
| `G:\gitTools\.venv-verinex-stage3\Scripts\python.exe -m pytest -q backend/tests/test_phase9_algorithms.py backend/tests/test_phase13_algorithms.py -k 'normaliz or dry_run or artifact or github or source_record or schema or mapping or registry' --tb=short` | **39 passed, 43 deselected** in 0.51 s. Deselected tests are not counted as passes. |
| `G:\gitTools\.venv-verinex-stage3\Scripts\python.exe -m scripts.verify_neon_sql_stage3 --output reports/verinex_neon_integration/STAGE_3_REMOTE.json` | **PASS**. Created disposable graph `verinex_neon_stage3_7bf1ada9`, tenant `neon-stage3`; fetched the real pinned file anonymously and completed two full pipeline ingestions. The evidence JSON was written. |
| `G:\gitTools\.venv-verinex-stage3\Scripts\python.exe -m scripts.verify_neon_sql_stage3 --graph verinex_neon_stage3_7bf1ada9 --output reports/verinex_neon_integration/STAGE_3_REMOTE.json` | **Failed before ingestion** on a later verification attempt: GitHub anonymous API rate limit (`GitHubApiError`), `fetched=0`. The prior PASS evidence file was retained and the stored graph was queried directly afterward. This does not negate the completed earlier live run. |
| `G:\gitTools\.venv-verinex-stage3\Scripts\python.exe -m compileall -q backend/app/ingestion/normalization/postgres_schema.py backend/app/ingestion/normalization/github.py backend/app/ingestion/provenance/service.py backend/app/ingestion/resolution/service.py backend/app/ingestion/writer/graph_writer.py scripts/verify_neon_sql_stage3.py` | PASS. |
| `git diff --check -- backend/app/graph/schema.py backend/app/ingestion/normalization/github.py backend/app/ingestion/provenance/service.py backend/app/ingestion/resolution/service.py backend/app/ingestion/writer/graph_writer.py requirements.txt` | PASS; only Git line-ending notices. |

The successful pipeline runs each reported `SUCCEEDED`, `fetched=2`, `normalized=2`, `written=2`, `quarantined=0`, `failed=0`, `artifacts=1`, and no warnings. Graph counts after run 1 and run 2 were identical: 15 `SqlTable`, 86 `SqlColumn`, 33 `SqlConstraint` (15 PK + 18 FK), 2 `SourceRecord`, 1 `Artifact`, 18 `FOREIGN_KEY_TO`, 15 `DEFINES`, 86 `HAS_COLUMN`, and 33 `HAS_CONSTRAINT`. A second `IngestionRun` is expected provenance and is not a duplicate schema entity.

## FalkorDB Cypher evidence

The successful live script compared all 15 stored table names and all 18 stored FK source/target/constraint/commit/hash tuples against the parsed source artifact. The following query returned a single path:

```cypher
MATCH (p:SqlTable {tenant_id:$tenant_id, name:'public.payment'})-[fk1:FOREIGN_KEY_TO]->
      (r:SqlTable {tenant_id:$tenant_id, name:'public.rental'})-[fk2:FOREIGN_KEY_TO]->
      (i:SqlTable {tenant_id:$tenant_id, name:'public.inventory'})-[fk3:FOREIGN_KEY_TO]->
      (f:SqlTable {tenant_id:$tenant_id, name:'public.film'})
RETURN p.name, fk1.constraint_name, r.name, fk2.constraint_name,
       i.name, fk3.constraint_name, f.name
```

Result: `public.payment → payment_rental_id_fkey → public.rental → rental_inventory_id_fkey → public.inventory → inventory_film_id_fkey → public.film`.

Read-only Cypher queries after the rate-limited retry also returned:

- `(repo:System)-[:CONTAINS]->(file:Document)-[:DEFINES]->(table:SqlTable)` = `neondatabase/postgres-sample-dbs`, `dvdrental.sql`, `public.payment`.
- `(file:Document)-[:DERIVED_FROM]->(artifact:Artifact)` = `dvdrental.sql`, SHA-256 `fa73f75e117e7f2af010ba7542b224d76897a17ac4972be257513c86ad4da12a`.
- All 18 `FOREIGN_KEY_TO` edges carried the exact SQL SourceRecord ID, pinned commit, blob SHA, file SHA-256 and successful second ingestion run ID. Their source/target columns were queried from stored edge properties and appear in the FK table above.

The disposable graph is left intact for inspection; no existing graph was reset or deleted. The rate limit temporarily blocks a fresh remote retry, but **live persistence verification is complete** from the successful two-run fetch and Cypher checks. No other blocker remains within Stage 3 scope.
