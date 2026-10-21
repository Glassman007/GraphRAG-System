# VERINEX Company Brain: Source control, pipeline, registry, normalization

## Scope and evidence

**Files under audit:** the three standalone Python files supplied in the current conversation and the 13 `.py` members of `normalization.zip`. Supporting models, helpers, and sample fixtures came from the prior `GraphRAG-System-main (4)(2).zip` archive. The archive predates the submitted code and does not contain all runtime dependencies. The offline test harness executes the actual submitted method/class bodies through AST extraction with mocks for the missing dependencies; all normalized candidate mappings except the pglast-based SQL parser are imported directly.

**Before changes:** 16 passed; 10 failed in the focused suite. **After changes:** 34 passed. These counts are offline/unit checks, **not** full production or live integration certification.

## Results by responsibility

| Component | Responsibility assessed | Evidence and result |
| --- | --- | --- |
| `source_control.py` | Register, configure, test, sync connected sources | Registration/configuration, connector allowlist, credential storage boundary, status reporting and sync wiring are present. Offline checks reproduced credential creation before validation, connection secret acceptance, and incorrectly asserting health for a configuration-only live probe. Patched. Live auth and FalkorDB-backed persistence remain unverified. |
| `pipeline.py` | Coordinate fetch, normalization, resolution and graph writing | Tested dry run with real database normalizer plus fake resolution, and persisted execution via injected provenance/graph writer. Reproduced unknown-mode fallthrough. Found page cursor advanced before all page records were processed, potentially skipping records after a crash (GitHub/Slack next-page cursors). Patched with page-level cursor checkpointing. Live graph/adapter integration not run. |
| `registry.py` | Choose and instantiate adapters | Registry type selection and instances verified with fake adapters. Reproduced half-registration if adapter construction throws. Reproduced resetting `DataSource.created_at` on every sync. Patched to publish registrations only after successful construction/persistence and preserve creation time in graph. Real FalkorDB query support not verified here. |
| `normalization.zip` | Convert source records into canonical graph entities and relationships | All eight registered normalizer types produced representative canonical entities and internally valid candidate relation endpoints. Reproduced disabled Slack/Teams authorship linkage and mislabeled Teams/Internal API mapping rules. Patched `slack.py`, `teams.py`, `internal_api.py`. pglast-backed SQL DDL parsing needs a repository-local test with `pglast` installed. |

## Confirmed defects fixed

1. `source_control.py`: secret-bearing `connection_config` keys at the top level or nested under lists/dicts were not rejected; even allowed HTTPS URLs could contain embedded credentials. Now rejected before graph writes.
2. `source_control.py`: invalid source creation mode or unsupported live connector could save credentials before rejection. Validation now precedes secret creation.
3. `source_control.py`: `test_connection()` interpreted configuration-only `health_check().ok` as verified live authentication and permissions. It now reports `UNVERIFIED` unless the adapter expressly verifies live checks. Fixture checks distinguish nonapplicable authentication from actual verification. **Adapters must implement real probes and return the relevant verified evidence for a live `HEALTHY` result.**
4. `source_control.py`: pipeline setup failures could leave sync status `RUNNING`. Setup exceptions now set `FAILED` and retain a sanitized error type before rethrowing.
5. `pipeline.py`: unsupported sync modes silently ran the full-sync path. Now rejected.
6. `pipeline.py`: page-level cursors could be persisted after processing just the first record. Now postponed until the whole page completes. This supports crash retry without skipping the rest of a page; already committed rows may be replayed, so writer idempotency remains necessary.
7. `registry.py`: adapter constructor/persist failures left a half-created in-memory registration. Now avoids publishing incomplete registrations.
8. `registry.py`: source creation timestamps were overwritten by repeat syncs. Now preserves the first `created_at` using a conditional Cypher `coalesce` update (requires live FalkorDB validation).
9. `normalization/slack.py`: a conditional `if False` disabled `author -PRODUCED-> message` edges, inherited by Teams. Enabled consistent authorship graph candidate creation; writer may still quarantine unresolved author identities.
10. `normalization/teams.py` and `internal_api.py`: `mapping_rule` carried parent-source prefixes (`slack:` / `database:`). It now uses `teams:` / `internal_api:`.

## Local offline regression command

From the VERINEX repository root, after applying patch files:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_company_brain_core_audit.py --tb=short
```

Additional relevant existing tests (use separate command and report exact blockers instead of rewriting unrelated code):

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_phase9_algorithms.py backend/tests/test_phase13_algorithms.py --tb=short
```

## Unverified items; do not assume PASS

- Full, real API/graph persistence for source create/update/connection/sync.
- Live adapter authentication, authorization and networking for GitHub/Jira/Slack/PostgreSQL; the submitted files delegate most of that to the adapter implementations.
- True PostgreSQL `pglast` SQL dump/schema parser behavior against the current sample file; pglast is unavailable in this offline sandbox. Previous successful database-ingestion evidence is not a fresh parser acceptance test.
- FalkorDB compatibility/semantics of conditional `DataSource.created_at` update.
- Crash recovery with the actual adapter pagination and durable checkpoint state, including idempotency and source update/delete handling.
- Full-repository regression suite against the user's most recent checkout; the older archive lacks later runtime modules and was used as a dependency scaffold only.

Use `docs/VERINEX_CODEX_LIVE_CHECK_PROMPT.md` for one bounded repository-local verification pass. **Do not perform schema migrations, send data to an LLM provider, or change the current production tenant in this audit.**
