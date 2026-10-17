# GraphHacks Phase 10, 11, and 1-11 Verification Bundle

Place these files in your repository's `scripts/` folder:

- `verify_phase10_browser.py`
- `verify_phase11_api.py`
- `verify_phases_1_11.py`
- `phase_test_manifest.json`

The Phase 10 and 11 scripts were built from the uploaded repaired Phase 11 repository and patched to tolerate FalkorDB's `Invalid graph operation on empty key` response when a fresh isolated graph name does not yet exist.

## Requirements

- FalkorDB running on `localhost:6379` unless `FALKORDB_HOST` / `FALKORDB_PORT` override it.
- Repository virtual environment active.
- Run from repository root.

## Phase 10 browser verification

```powershell
python scripts\verify_phase10_browser.py
```

It creates an isolated graph, leaves `company_brain` untouched, and writes:

- `phase10_acceptance_report_<graph>.json`
- `phase10_browser_queries_<graph>.cypher`

Open FalkorDB Browser at `http://localhost:3000`, select the printed graph, and run the generated Cypher.

## Phase 11 API/browser verification

```powershell
python scripts\verify_phase11_api.py
```

It uses FastAPI `TestClient`; Uvicorn is not required. It creates an isolated graph and writes:

- `phase11_api_acceptance_<graph>.json`
- `phase11_api_examples_<graph>.http`
- `phase11_browser_queries_<graph>.cypher`

## Phases 1-11 smoke verification

Representative live tests for every phase:

```powershell
python scripts\verify_phases_1_11.py --mode smoke
```

By default, any skipped test causes that phase to fail. This is intentional for your local machine because FalkorDB is expected to be available.

## Complete Phase 1-11 test verification

The manifest covers every `backend/tests/test_*.py` file in the repaired Phase 11 repository exactly once.

```powershell
python scripts\verify_phases_1_11.py --mode full
```

The repaired repository reports **667 collected tests**. On your live local FalkorDB setup the target is:

```text
667 passed
0 failed
0 skipped
```

## Full tests plus Phase 10/11 live acceptance

After replacing the repository's Phase 10/11 acceptance scripts with the patched copies in this bundle:

```powershell
python scripts\verify_phases_1_11.py --mode full --with-browser
```

This runs the phase-by-phase pytest suite and then the isolated Phase 10 and Phase 11 acceptance runners.

## Run a subset

```powershell
python scripts\verify_phases_1_11.py --mode smoke --from-phase 6 --to-phase 11
```

## Reports

The master runner creates:

```text
phase1_11_verification_<timestamp>/
    phase_01.log
    phase_02.log
    ...
    phase_11.log
    phase_10_browser.log     # with --with-browser
    phase_11_browser.log     # with --with-browser
    phase1_11_report.json
```

`company_brain` is not used by the pytest integration fixture: it generates temporary `company_brain_test_<id>` graphs. Phase 10 and 11 browser/API runners likewise create separate isolated graphs.
