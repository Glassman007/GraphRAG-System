# Phase 12 UI Acceptance

## Unit/component tests

```powershell
cd frontend
npm install
npm test
npm run typecheck
npm run build
```

## Live browser acceptance

Install Chromium once:

```powershell
cd frontend
npx playwright install chromium
cd ..
python scripts/verify_phase12_ui.py
```

The runner creates `phase12_accept_<random>` and never writes to `company_brain`. It seeds the established Northstar fixture plus one graph-scoped retrieval artifact and a deterministic Task, starts the real FastAPI app and Vite UI, runs `frontend/e2e/phase12.spec.ts`, writes an acceptance JSON report and FalkorDB Browser query file, then stops the processes while leaving the isolated graph for inspection.

The Playwright story covers Situation -> Investigation -> graph-first retrieval -> Evidence/provenance -> Claim conflict/authority -> Plan/Task graph -> Agent -> Decision genealogy -> Action governance -> Blast Radius -> Simulation -> Company Brain analytics -> Anomalies.

The final step changes backend state through the real external API and verifies the Situations UI changes after navigation. This is the explicit proof that the frontend is not driven by static demo objects.
