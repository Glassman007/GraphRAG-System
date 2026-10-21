# VERINEX Company Brain — targeted graph layer patch

## Scope and verification

Reviewed uploaded versions of `graph_writer.py`, `client.py`, `schema.py`, `mutations.py`, `queries.py`.

- All five parsed successfully.
- `client.py`: correct wrapper structure (connect/query/ro_query/health/delete); mocked connection/query routing tested. Actual FalkorDB compatibility and connectivity **not tested**.
- `schema.py`: permitted node labels, relationship types, unique identity constraint and 22 range indexes exist; mocked index invocation tested. Index creation on FalkorDB **not tested**.
- `mutations.py`: node/edge upsert and delete Cypher generated; tenant override flaw reproduced and fixed.
- `queries.py`: get entity, neighbors, generic dependency traversal, dependents, owner, expert/claims/evidence/conflict/policy/history, arbitrary paths implemented; mocked query construction tested. `get_dependencies`/`get_dependents` only traverse `DEPENDS_ON`, not SQL `FOREIGN_KEY_TO` edges. Confirm service-level SQL behavior before changing their default semantics.
- `graph_writer.py`: normalized canonical nodes and relationships, source lineage, structural claims and evidence, authority promotion paths, tombstone evidence. Mocked node write/claim/evidence flow tested. Four graph-integrity defects described below were reproduced and patched.

No live FalkorDB server or complete VERINEX repository was available for this audit. A mocked PASS does not establish actual database semantics or end-to-end ingestion success.

## Fixes (two replacement files)

1. `backend/app/graph/mutations.py`: prevent caller-provided `tenant_id` from changing the tenant associated with the active client. Raises ValueError before any database call.
2. `backend/app/ingestion/graph_writer.py`:
   - Include source actor ID in both observed and authoritative evidence IDs to avoid merging different structural facts sourced from the same record.
   - Store the asserted actor, predicate, target, and source record as evidence properties for provenance.
   - Do not automatically create `CONTRADICTS` when distinct actors depend on the same target. An explicit `config.settings['exclusive_structural_relationship_types']` opt-in enables the old exclusivity test for a relation type declared to be single-owner by a documented ontology policy. Leave this setting unset otherwise.
   - When a canonical relationship has authoritative=true, accept new low-trust source-record provenance without overwriting accepted authority, confidence, timestamps, or source attribution. An authoritative upgrade to a previously non-authoritative relationship updates source attribution.

## Applying in your repo (Windows PowerShell)

Unzip at the VERINEX repository root, preserving folder structure, **after reviewing the diff and backing up existing files**:

```powershell
Expand-Archive -Path .\VERINEX_Graph_Layer_Fixes.zip -DestinationPath . -Force
python -m pytest -q backend/tests/test_company_brain_graph_regressions.py --tb=short
```

If `graph_writer.py` lives outside `backend/app/ingestion/` in your checkout, copy that file to its actual import location rather than keeping a duplicate. These replacement files were created from the provided uploads, **not merged against a live checkout**. Compare against any uncommitted local changes first.

## Verified local regressions

Seven focused regression tests passed in a dependency-stubbed environment. Tests use recording clients / graph snapshots rather than a real database. They cover cross-tenant upsert refusal, evidence ID uniqueness, non-exclusive dependencies, explicit exclusive ownership, lower-trust downgrade prevention, authoritative upgrades, and fact-specific authoritative evidence.

## Still requires testing in full repo

- Confirm FalkorDB library/server versions and support for `.ro_query`, composite unique constraints and all generated Cypher patterns (`UNION`, bounded traversal, map-property updates).
- Perform source ingestion/resync into a disposable test graph. Check exact node/edge identity, graph provenance, ownership promotion, tombstones, multiple distinct foreign keys, and SQL dependencies.
- Check SQL entity writes in `graph_writer.py`: `SqlTable`, `SqlColumn`, `SqlConstraint` intentionally bypass the ordinary existing-node guard. Verify how lower-trust source metadata is handled and whether schema refresh should overwrite accepted facts.
- Check repeated full `GraphSnapshot.load()` calls for large-graph ingestion latency, and ensure stale snapshots do not misrepresent success.
- Verify `upsert_relationship()` returning `None` for missing endpoints is not reported as a successful relationship write by callers.
- Confirm relation cardinality policy before enabling any exclusive structural contradiction detection.

See `Codex_Live_Graph_Verification_Prompt.md` for a budget-conscious verification procedure.
