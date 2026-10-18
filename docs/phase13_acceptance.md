# Phase 13 Acceptance

Run `python scripts/verify_phase13_ui.py`. The runner creates an isolated `phase13_accept_<random>` FalkorDB graph, applies schema, starts the real API and frontend, and executes `frontend/e2e/phase13.spec.ts`. It never mutates `company_brain`.

The story covers first-run onboarding, GitHub fixture source creation, connection test, scope/mapping, dry-run preview, initial sync, run/record inspection, identity resolution, Company Brain/entity presentation, provenance, investigation/retrieval presentation, Technical Mode, risk presentation, disable/re-enable, and second sync history.

Sandbox status in this build: cannot run because the FalkorDB Python client/server is unavailable. This is a required local verification gate, not a pass.
