# Stage 2: public GitHub repository and file retrieval

Date: 2026-10-21 (Asia/Calcutta). Starting commit: `065aadd407c2cd9d8653c0baf635d9955c93b18c`.

**Stage 2 acceptance passed against the actual remote repository without authentication.** VERINEX retrieved `dvdrental.sql`, identified its source path and immutable commit/blob, and verified the downloaded bytes against the Git blob SHA. No SQL was parsed/executed and no FalkorDB or frontend changes were made.

## Changed files

| File | Change |
| --- | --- |
| `backend/app/ingestion/adapters/github.py` | Public anonymous or optional authenticated access; repository URL/owner/name parsing; real repository/org health requests; default or selected branch/ref resolution to a commit; regular-file tree discovery; selected immutable blob downloads as source-file artifacts; stable cursors and fixed-size organization pagination. Fixture delegation remains available. |
| `backend/app/ingestion/adapters/github_http.py` | GitHub-only HTTPS/host validation, no redirects, 10-second socket timeout, bounded JSON responses, sanitized HTTP/network errors, and rate-limit/reset details. Existing shared connector HTTP transport was left untouched. |
| `backend/app/ingestion/source_control.py` | Accept/normalize explicit GitHub repository configuration; advertise anonymous/files support; preserve actual adapter health statuses, checks, commit and retry details in connection-test responses. |
| `backend/tests/test_github_connector_stage2.py` | 64 focused cases for scope validation, anonymous/authenticated requests, health/failures, file content/integrity, discovery, branch and commit pinning, filtering, record-level resume, changed batch sizes/scope, transport limits and source-control integration. |
| `scripts/verify_neon_github_stage2.py` | Repeatable live anonymous health/discovery/two-page repository-and-file fetch with optional JSON evidence output. Performs no graph writes or SQL execution. |
| `reports/verinex_neon_integration/STAGE_2_REMOTE.json` | Actual remote verification evidence, including sizes, hashes, commit and immutable URL; excludes SQL contents and credentials. |
| `reports/verinex_neon_integration/STAGE_2_RESULTS.md` | This implementation, verification and compatibility record. |

No new packages are required. Stage 1's pre-existing tracked modifications/deletions and untracked files were preserved. At Stage 2 entry, the tree contained 123 tracked deletions, 16 tracked modifications, 50 untracked files (including `BASELINE.md`), and an empty staging index. The two modified tracked Stage 2 files were clean at entry. Only the seven files above are intended for the Stage 2 commit; unrelated files and the existing untracked acceptance tests/baseline are excluded.

## Configuration contract and use

For direct adapter use:

```python
from backend.app.ingestion.adapters.github import GitHubAdapter
from backend.app.ingestion.models import SourceConfig

config = SourceConfig(
    id="neon", source_type="github", name="Neon samples", source_instance="neon",
    settings={
        "repository": "https://github.com/neondatabase/postgres-sample-dbs",
        "anonymous": True,
        "files": ["dvdrental.sql"],
    },
)
adapter = GitHubAdapter(config)
health = adapter.health_check()
discovery = adapter.discover_files()  # Tree metadata only; no blob downloads.
page = adapter.fetch(limit=10)       # Repository + selected SQL-file artifact.
```

The existing source API can use `connector_type="github"`, `connection_mode="live"`, `connection_config.settings` containing `repository`, `anonymous` and optional `branch`/`ref`, and `scope_config.files=["dvdrental.sql"]`. Direct connection fields such as `connection_config.repository_url` are also normalized into settings. `owner` + `repo` is accepted. The default API base URL is `https://api.github.com`.

- Repository input supports `owner/repo`, a github.com HTTPS repository URL, and optional `.git` suffix. Owner/name comparison is case insensitive. Unsupported hosts, embedded credentials, extra URL path components and traversal are rejected.
- Authentication is optional when no credential is available. `anonymous=True` explicitly suppresses both credential-store and environment tokens. Otherwise existing stored-token / token-environment behavior is retained. Credentials rejected by GitHub do not silently fall back to anonymous.
- Omit `branch`/`ref` to resolve the repository's default branch. Use `branch` for a selected branch or `ref` for an explicit commit/ref. The resolved full commit SHA and tree SHA are retained; full SHA requests have no branch attribution. Health reports the default `main` branch in the live evidence. The live script then requests its exact SHA, so the resulting file record correctly has `branch=null` with that SHA as `ref`.
- `files` selects exact relative, case-sensitive regular-file paths. Symlinks and submodules are not downloaded. With no files selected, fetch emits repository metadata; `discover_files()` still enumerates the tree. The entire dump is downloaded as a bounded artifact, with no interpretation of SQL or COPY rows.
- A `sql_file`/`source_file` envelope includes repository, source path, commit SHA, blob SHA, size, SHA-256, immutable `blob/{commit}/path` URL, and a `SOURCE_FILE` artifact containing the bytes. File identities remain repository/path based, with commit in the version/provenance fields.
- `scope_config.selected` retains its previous role as an **organization repository filter**. Direct fetching uses explicit `repository`/`repository_url` or `owner`+`repo`; a filter alone does not change discovery mode.
- Organization requests always use `per_page=100`, sort by full name, and continue across empty filtered pages inside the adapter. New cursors encode page+record offset; caller batch-size changes or resuming from an individual committed record cannot skip the rest of that page. Repository cursors pin commit/ref and offset. File-selection order is normalized; changing actual scope invalidates the cursor. Organization membership remains mutable upstream, so concurrent repo additions/removals are not an immutable snapshot guarantee.
- Legacy numeric organization page cursors are accepted, but their old variable page-size history is unknowable; start a full sync when migrating an existing live source to v2. `GitHubAdapter.adapter_version` is `github-v2`; existing persisted source config version fields are not automatically migrated in this stage.

## Failure handling and limits

Health executes real API GETs before claiming success. Source-control connection tests forward the adapter's `HEALTHY`, `AUTH_FAILED`, `PERMISSION_ERROR`, `NOT_FOUND`, `RATE_LIMITED`, `TIMEOUT`, `UNREACHABLE`, `API_ERROR`, or `INVALID_RESPONSE` status. Anonymous success reports authentication `NOT_REQUIRED`. An HTTP failure can report reachability PASS while API access is FAIL; these are no longer inferred from credential-shaped configuration alone.

HTTP 403 exhaustion/secondary limits and 429 return rate-limit errors with available `Retry-After` and reset values. There is no automatic retry loop or sleep; the caller can retry later with the last committed cursor. Error bodies, tokens and full network exceptions are not echoed. Missing/inaccessible repository/ref/file is explicit; no empty-success substitute is fabricated.

File size is limited to 20 MiB by default (configurable downward with `max_file_bytes`), JSON transport to 32 MiB, and one organization discovery call to 100 upstream pages. Oversized responses/files and truncated recursive trees fail explicitly. Truncated-tree fallback and fetching larger files are not implemented. The endpoint shape follows GitHub's [tree](https://docs.github.com/en/rest/git/trees) and [blob](https://docs.github.com/en/rest/git/blobs) APIs; downloads verify declared size and Git blob hash before returning an artifact. All HTTP redirects are rejected, so renamed/transferred repositories must be configured with their canonical repository URL.

## Tests and real remote evidence

Commands ran from `G:\graphhacks` with the existing Python environment; no full repository suite or dependency installation was performed.

| Exact command | Result |
| --- | --- |
| `python -m pytest -q backend/tests/test_github_connector_stage2.py --tb=short` (initial development run) | 60 passed, 1 failed: cursor scope incorrectly depended on file-selection order. Fixed by hashing canonical scope; additional regressions were subsequently added. |
| `python -m pytest -q backend/tests/test_github_connector_stage2.py backend/tests/test_phase9_algorithms.py backend/tests/test_phase13_algorithms.py --tb=short` | 142 passed, 1 failed in 6.42 s. The failure was existing `test_phase9_api_routes_exist_without_arbitrary_sql_or_url_ingestion`, caused by route enumeration compatibility described below. |
| `python -m pytest -q backend/tests/test_github_connector_stage2.py backend/tests/test_phase9_algorithms.py backend/tests/test_phase13_algorithms.py -k 'stage2 or adapter or github or database or connector or source_registry or credential' --tb=short` | **104 passed, 42 deselected**, in 2.67 s. This is the final connector-focused gate: 64 new tests plus the 40 existing connector-related tests used in Stage 1. No skipped tests were counted as passes. |
| `python -m pytest -q test_verinex_neon_acceptance.py -k 'test_01 or test_02 or test_03 or test_04' --tb=short` | **2 passed, 2 failed, 3 deselected**, in 1.26 s. Tests 01/02 now pass. Tests 03/04 have the configuration/page-size assumptions documented below; original tests were preserved. |
| `python -m scripts.verify_neon_github_stage2 --output reports/verinex_neon_integration/STAGE_2_REMOTE.json` | **PASS**, exit 0, both before and after final cursor refinements. Latest evidence: 2026-10-21 16:01:24 UTC (21:31:24 IST). Anonymous live repository health, full regular-file discovery and repository/file fetch using `limit=1` with cursor resume all succeeded. |

Actual remote result:

| Field | Observed value |
| --- | --- |
| Repository | `neondatabase/postgres-sample-dbs` |
| Default branch | `main` |
| Commit | `b54cb67534bf20775803b181b7a1c6f573422161` |
| Selected path | `dvdrental.sql` |
| Blob SHA | `5fe9c6fee0ba073362952964edd04a6527c24aee` |
| Content bytes | `2760206` |
| Content SHA-256 | `fa73f75e117e7f2af010ba7542b224d76897a17ac4972be257513c86ad4da12a` |
| Regular files discovered | 14; includes `dvdrental.sql`, `pagila.sql`, `chinook.sql` |
| Source URL | `https://github.com/neondatabase/postgres-sample-dbs/blob/b54cb67534bf20775803b181b7a1c6f573422161/dvdrental.sql` |

The live check validated nonempty downloaded bytes, the PostgreSQL dump header, actual source path, commit, SHA-256 and the transport's Git blob integrity check. Mock tests cover negative HTTP/network scenarios and organization pagination; these negative scenarios were not deliberately induced against the real remote service.

## Compatibility failures and blocked checks

1. The existing route test assumes every `app.routes` item has `.path`. Installed FastAPI is **0.139.2**, while `requirements.txt` specifies `>=0.128,<0.129`. Its `_IncludedRouter` objects do not expose that attribute. Loading both modified tracked modules from the starting commit into a separate Python process and rerunning just this test still produced the same `AttributeError` (1 failed in 2.43 s). No route, unrelated test or dependency was changed to hide it. Reproducer used:

   ```powershell
   @'
   import subprocess, sys, types
   from pathlib import Path
   import pytest
   for name, filename in [
       ('backend.app.ingestion.adapters.github', 'backend/app/ingestion/adapters/github.py'),
       ('backend.app.ingestion.source_control', 'backend/app/ingestion/source_control.py'),
   ]:
       source = subprocess.check_output(['git', 'show', '065aadd:' + filename], text=True, encoding='utf-8')
       original = types.ModuleType(name)
       original.__file__ = str(Path(filename).resolve())
       sys.modules[name] = original
       exec(compile(source, filename, 'exec'), original.__dict__)
   raise SystemExit(pytest.main(['-q', 'backend/tests/test_phase9_algorithms.py::test_phase9_api_routes_exist_without_arbitrary_sql_or_url_ingestion', '--tb=short']))
   '@ | python -
   ```

2. Supplied Neon test 03 supplies `org` and `scope_config.selected`, then requires a direct-repo endpoint. Preserving organization filtering means this remains a listing request. Explicit `repository` configuration is now tested with the exact endpoint, content and provenance, including the real remote fetch. This is an intentional configuration contract clarification rather than an assertion that the original test passed.
3. Supplied Neon test 04 returns two rows and assumes that is a full upstream page because caller `limit=2`. Stable pagination now always requests 100 upstream rows, so two rows correctly indicate the final short page. Its original fixture cannot prove a later page exists under that contract. The focused regression returns 100 nonmatching rows on page 1, then the selected repository on page 2, and verifies it is actually retrieved. Record-level partial-page resume and changed caller limits are also tested.

No Stage 2 remote check was blocked by network or credentials. SQL parsing, table/FK normalization, canonical graph persistence, UI changes and live PostgreSQL behavior are outside this stage and were not claimed as passed. In particular, the existing GitHub normalizer still quarantines `sql_file` records during canonical sync; this stage proves connector content retrieval, not Company Brain schema ingestion. The other three supplied SQL/database acceptance cases were deselected, not passed.

The Stage 2 commit is limited to the seven listed files; the final response supplies its generated commit ID. No push is performed.
