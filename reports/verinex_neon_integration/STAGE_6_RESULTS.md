# Stage 6: live PostgreSQL schema ingestion

**PASS** for a running, disposable PostgreSQL 16 database and isolated FalkorDB graph. VERINEX registered the database through Sources, tested a real read-only connection, read `pg_catalog`, completed two syncs, and served the graph through Company Brain. This was a local PostgreSQL instance containing the DVD rental schema, not a connection to a hosted Neon database. No table rows were ingested.

## Confirmed defects and fixes

- `DatabaseAdapter.health_check()` previously treated a configured DSN as proof of health. It now connects, checks that the transaction is read-only, and reads `pg_catalog`; connection or catalog failure cannot report healthy.
- The live adapter previously supported only a server-registered row query. A server-registered **schema** mode now reads scoped table, column, primary-key and foreign-key definitions from PostgreSQL catalogs in a read-only repeatable-read transaction. The existing row-query mode is retained and now uses the same enforced read-only connection.
- `DatabaseNormalizer` previously quarantined structural database records. It now maps the catalog snapshot into existing `System` → `Document` → `SqlTable` / `SqlColumn` / `SqlConstraint` entities and actual `FOREIGN_KEY_TO` relationships. Source IDs and database-qualified canonical IDs keep these facts distinct from the GitHub SQL-file facts.
- The existing graph writer now gives database-schema relationships deterministic constraint-aware edge IDs, so a repeat sync reuses them. The server-side schema registry prevents API callers from supplying arbitrary SQL, DSNs or schema scope.

Files modified: `backend/app/ingestion/adapters/database.py`, `backend/app/ingestion/normalization/database.py`, `backend/app/ingestion/source_control.py`, `backend/app/ingestion/writer/graph_writer.py`, `requirements.txt` (`psycopg[binary]>=3.2,<4`). Focused test and verifier: `backend/tests/test_neon_database_stage6.py`, `scripts/verify_neon_postgres_stage6.py`. This report is the only Stage 6 report. Existing GitHub retrieval, SQL parsing, graph ontology, frontend, and stored graphs were left intact. No Git reset, clean, restore, commit or push was performed.

## Live evidence

The verifier checked the SHA-256 of the existing Stage 3 `dvdrental.sql` artifact and used its extracted **DDL only** to create a fresh PostgreSQL container/database. It did not execute the downloaded dump or its COPY data. VERINEX then connected as a separate `verinex_reader` role with no schema CREATE privilege; the container was stopped after verification. The new FalkorDB graph remains available as `verinex_neon_stage6_f7794062`, tenant `neon-stage6-f7794062`, source `SRC-NEON-STAGE6-F7794062`.

| Check | Observed result |
| --- | --- |
| Sources connection test | `HEALTHY`, live PostgreSQL request, read-only transaction and catalog access |
| PostgreSQL catalog | 15 tables, 18 foreign-key constraints |
| Each of two normal Sources syncs | `SUCCEEDED`; 1 fetched, 1 normalized, 1 written, 0 quarantined, 0 failed |
| FalkorDB after the second sync | 15 `SqlTable`, 86 `SqlColumn`, 33 `SqlConstraint`, 18 `FOREIGN_KEY_TO` |
| Company Brain API | `GET /api/v1/company-brain/sql-schema?source_id=...` returned 15 tables and 18 FKs; payment detail returned columns, constraints, database catalog source and PostgreSQL system provenance |
| Stage 5 comparison | Table names and `(source table, constraint name, target table)` FK sets match the stored GitHub-derived graph exactly; canonical table IDs are disjoint |

The direct tenant-scoped FalkorDB path query returned `public.payment`, `public.rental`, `public.inventory`, `public.film`:

```cypher
MATCH (p:Entity:SqlTable {tenant_id:$tenant_id, name:'public.payment'})-[:FOREIGN_KEY_TO]->
      (r:Entity:SqlTable {tenant_id:$tenant_id, name:'public.rental'})-[:FOREIGN_KEY_TO]->
      (i:Entity:SqlTable {tenant_id:$tenant_id, name:'public.inventory'})-[:FOREIGN_KEY_TO]->
      (f:Entity:SqlTable {tenant_id:$tenant_id, name:'public.film'})
RETURN p.name,r.name,i.name,f.name
```

The graph relationship properties and payment detail include the source-derived constraint names and definitions. The read-only role supplied no table content to the ingestion adapter. Repeating the full sync did not increase schema entity or FK edge counts.

## Tests executed

From `G:\graphhacks`:

| Exact command | Result |
| --- | --- |
| `G:\gitTools\.venv-verinex-stage3\Scripts\python.exe -m pytest -q backend/tests/test_neon_database_stage6.py backend/tests/test_phase9_algorithms.py::test_phase9_database_mapping_uses_team_and_system_not_vendor_types backend/tests/test_phase9_algorithms.py::test_phase9_database_adapter_contract_is_read_only backend/tests/test_phase13_algorithms.py::test_phase13_live_database_rejects_user_sql --tb=short` | **6 passed** in 0.62 s |
| `G:\gitTools\.venv-verinex-stage3\Scripts\python.exe -m scripts.verify_neon_postgres_stage6` | **PASS**, final run; real PostgreSQL, two API syncs, direct Cypher counts/path, Company Brain API and Stage 5 comparison |
| `git diff --check -- backend/app/ingestion/adapters/database.py backend/app/ingestion/normalization/database.py backend/app/ingestion/source_control.py backend/app/ingestion/writer/graph_writer.py requirements.txt` | **PASS**; Git reported only line-ending notices |

The first verifier attempt failed while constructing the disposable fixture because foreign keys were applied before referenced primary keys. The fixture setup was corrected to create all primary keys first; the final live run passed. No existing database or graph was changed by that failed setup.

**Remaining blockers:** None for this local live PostgreSQL workflow. A hosted Neon PostgreSQL connection was not provided or tested. The existing anonymous GitHub rate limit from Stage 5 is separate and was not retried.
