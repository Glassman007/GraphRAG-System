# Phase 11 Manual Acceptance

## Automated isolated acceptance

Run with FalkorDB available:

```powershell
python scripts/verify_phase11_api.py
```

The script creates an isolated `phase11_api_accept_<random>` graph and does not modify `company_brain`. It generates:

- `phase11_api_acceptance_<graph>.json`
- `phase11_api_examples_<graph>.http`
- `phase11_browser_queries_<graph>.cypher`

## Swagger

Start the API and open:

```text
http://127.0.0.1:8000/docs
```

Use development credentials only outside production, for example:

```text
Authorization: Bearer test-admin-token
X-Tenant-ID: northstar
```

Suggested flow:

1. `GET /api/v1/capabilities`
2. `GET /api/v1/ready`
3. `GET /api/v1/situations/INC-001`
4. `POST /api/v1/investigations`
5. `POST /api/v1/investigations/{id}/retrieve`
6. inspect returned Evidence/provenance
7. inspect `SYS-PRICING-API`
8. find a bounded path to Pricing DB
9. run blast radius
10. inspect Claims/conflicts
11. create/inspect a Plan and Task
12. claim/start/checkpoint Task through Phase 6
13. inspect Decision genealogy
14. propose and execute governed sandbox Action; repeat to verify idempotency
15. run counterfactual and bus-factor simulations
16. query historical entity state
17. reconstruct `INC-001` and verify `BEFORE` remains distinct from `CAUSE`
18. inspect `POL-DB-04` drift
19. inspect bus-factor/bottleneck/bridge/collision/ownership-gap risks
20. test pagination, unauthorized access, cross-tenant rejection, invalid ID, and `X-Request-ID` propagation.

## Example curl

```bash
curl -H "Authorization: Bearer test-reader-token" \
     -H "X-Tenant-ID: northstar" \
     http://127.0.0.1:8000/api/v1/situations/INC-001
```

Never embed production credentials in demo files.
