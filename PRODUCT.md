# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Primary: hackathon judges** of the WeMakeDevs × FalkorDB "Graph Hacks" hackathon (Oct 15–18, 2026). They watch a short demo video and may open a live deployment or a local setup. Their job is to decide, quickly, whether the graph is actually doing the reasoning. Confirmed by the team: the frontend is built "judges first".
- **In-world users: engineering and incident operators** at the synthetic company "Northstar" (incident responders, engineering leads, system owners). They investigate situations, trace claims to evidence, coordinate tasks and run what-if simulations. Every screen must still work for this job on real backend data.

## Product Purpose

GraphHacks is a graph-native "Company Brain" built on FalkorDB. It turns fragmented organizational data into one temporal, provenance-aware graph: incidents, systems, teams, people, claims, evidence, tasks, decisions, policies, documents, telemetry and events. It can reason over relationships, retrieve supporting evidence, coordinate work and learn from validated outcomes.

Success for the frontend means a judge understands within the first 30 seconds that answers come *from the graph*: the traversal, the evidence chain and the provenance are all visible. It also means every screen stays a working client of the real API.

## Positioning

FalkorDB decides what is connected and where to look. Retrieval, planning, coordination and the UI all work on top of the graph instead of replacing it. Every answer can show the path it came from: graph scope, evidence, source records and the query that ran. The product does not work without FalkorDB.

Hackathon fit: Track 03 "Company Brain" (people, teams, decisions, sourced answers, keeping knowledge current). It also overlaps Track 01 (agents acting on connected data) and Track 02 (memory and coordination). *Open decision: which tracks are formally entered.*

## Operating Context

- The frontend is a React 18 + Vite + TypeScript SPA (`frontend/`) using TanStack Query, React Router and Cytoscape. It talks only to the FastAPI Phase 11 API under `/api/v1`, which Vite proxies to `127.0.0.1:8000` in dev.
- The backend is FastAPI over FalkorDB (Docker, graph `company_brain`, tenant `northstar`).
- Local auth uses test bearer tokens (`test-admin-token`, `test-reader-token`) and the `X-Tenant-ID` header.
- Existing screens: Situations (+ detail), Investigations, Work (plans, tasks, agents), Knowledge (claims, evidence), Decisions, Entities (+ relationships, provenance, history, blast radius), Simulations, Company Brain analytics (processes, policy drift, commitments, ownership gaps, expertise, bus factor, bottlenecks, bridges, duplicate initiatives) and Anomalies.
- Planned: a new landing / intro surface for the demo. Confirmed by the team.
- Hackathon submission needs a public repo, a README with setup, data model and the Cypher used, a demo video, a preferred live deployment, and disclosure of AI-assistant use.

## Capabilities and Constraints

- The browser requests, renders, inspects and operates. It must never reimplement backend reasoning (blast radius, authority/conflict resolution, process reconstruction, policy drift, risks, anomalies, retrieval, simulation, genealogy, governance).
- Preserve: API calls, payload shapes, query/route params, mutation behavior, permission checks, backend state checks, `as_of` temporal semantics, provenance, graph edge semantics, confirmation flows, idempotency and tenant/auth headers.
- `frontend/src/api/`, `auth/`, `graph/adapters.ts`, `permissions.ts` and `queryClient.ts` are functional infrastructure. Do not change them unless there is a genuine bug.
- Consequential actions keep their confirmation step and update the UI only after the backend succeeds. No fake optimistic success.
- No static demo data in the app, and no N+1 request patterns.
- Acceptance gates: `npm run typecheck`, `npm test`, `npm run build` and `python scripts/verify_phase12_ui.py` (Playwright selectors use visible text and roles).
- Deadline: submissions close **Oct 18, 2026, 11:59 PM IST**.

## Brand Commitments

- Name: **GraphHacks**. It is built on **FalkorDB**, which can be credited but must not be impersonated.
- Visual constraint set by the team: an **ASCII-world + Matrix-world fusion with Matrix rain**. On working screens the rain is ambient and gives way to data. The landing surface may run it at full intensity.

## Evidence on Hand

- A seeded synthetic dataset (`fixtures/`, `scripts/seed_*.py`): the Northstar company, with INC-001 (checkout failures after a pricing-database migration), SYS-PRICING-API, SYS-PRICING-DB, claims C-001/C-002, evidence E-003/E-004, decision DEC-INC001-ROLLBACK, tasks, agents, policies (POL-DB-04), commitments (COM-017) and initiatives (PROJ-REFUND-A/B).
- All of this data is synthetic. Do not present it as a real customer, and do not invent customers, testimonials, benchmarks or performance numbers. FalkorDB's own benchmark claims are not ours to quote.

## Product Principles

1. **Prove, don't claim.** Every answer shows the graph path, the evidence and the source it came from.
2. **The backend is the authority.** The UI renders reasoning; it never fakes or recomputes it.
3. **Time is a first-class dimension.** Any view that can be historical honors `as_of`.
4. **Governed by default.** State-changing actions are explicit, confirmed and permission-aware.
5. **Thirty seconds to conviction.** A judge should see a real question answered from the graph before anything else.

## Accessibility & Inclusion

No product-specific standard was set. *Assumed baseline:* WCAG 2.2 AA contrast; `prefers-reduced-motion` respected, with all rain and decode motion skippable; no flashing above three times per second; status never conveyed by color alone.
