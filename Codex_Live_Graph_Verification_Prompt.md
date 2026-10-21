# Codex prompt — VERINEX Company Brain graph layer verification

You are in the full VERINEX repo. Verify **only** these capabilities and the patch (no new features/refactors unless a test demonstrates a defect):

- `backend/app/graph/client.py`: configure/connect to FalkorDB; execute read/write/health-check.
- `backend/app/graph/schema.py`: allowed ontology types; graph indexes and tenant identity constraints.
- `backend/app/graph/mutations.py`: safely upsert/delete canonical graph entities/edges; prevent cross-tenant writes.
- `backend/app/graph/queries.py`: get entities, neighbors, ownership, generic dependencies/dependents, paths, history, evidence; determine whether SQL `FOREIGN_KEY_TO` must be traversable via these helpers or is handled elsewhere.
- `backend/app/ingestion/graph_writer.py`: create canonical nodes/relationships and source-evidence graph, maintain lineage/trust, handle tombstones/resyncs.

**Token/cost constraints:** Start with these five files and their direct imports; do not dump the repository. Use `rg --files backend/tests | rg 'graph|ingestion|schema|source'` only to select a few relevant existing tests. Avoid any model/LLM calls. Run focused pytest once after inspection and once after any fixes; use `-q --tb=short`. Do not run the full suite, rebuild a deployment, or generate long logs unless narrowly necessary. For any failure, include the short traceback and the file/line that establishes the root cause; no speculative changes.

Steps:

1. Confirm the patch is at the actual import paths, then run:
   `python -m pytest -q backend/tests/test_company_brain_graph_regressions.py --tb=short`
2. Verify file responsibilities (note: `mutations.py` performs mutations and validates type membership; `schema.py` alone defines types and indexes). Select at most 3-5 directly related repo tests to cover ingestion and graph queries.
3. If a local FalkorDB test instance is available, create an **isolated disposable graph with a unique name** and tenant IDs, never the user's active/production graph. Confirm connection, `apply_schema()` twice (idempotence), composite identity uniqueness, allowed label/relationship validation, node/edge upserts, query execution, historical `get_owner`, bidirectional `find_paths`, `get_dependencies`/`get_dependents`, and tenant isolation. Run cleanup **only** on your isolated test graph.
4. In that isolated graph, ingest two records supporting the same canonical entity and two distinct facts about one target. Assert correct source-record provenance, distinct evidence IDs, resync idempotence, and no false `CONTRADICTS` for non-exclusive relationships. Assert an untrusted observation cannot downgrade an authoritative relationship; assert a later authoritative observation can upgrade an untrusted one.
5. Exercise SQL schema graph with at least two tables and two distinct foreign-key constraints between them. Check `FOREIGN_KEY_TO` edge identity and source evidence, plus incoming FK discovery. Investigate whether `queries.get_dependents()` must support `FOREIGN_KEY_TO`; if not, name the actual downstream helper/service that does. Do **not** silently change `DEPENDS_ON` semantics to include every SQL FK.
6. Exercise tombstones (canonical entities must not be deleted) and missing-endpoint writes (do not report skipped graph edges as written). Verify that existing `SqlTable`/`SqlColumn`/`SqlConstraint` facts are not incorrectly overwritten by lower-trust ingestions.

Return a compact result table with **PASS / FAIL / UNTESTED**, test commands, exact defects/reproductions, file:line evidence, and remaining risks. Make only minimal, explicitly justified edits. Do not claim live PASS when no FalkorDB service was available.
