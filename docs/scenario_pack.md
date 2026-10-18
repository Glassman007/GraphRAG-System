# Scenario Pack

## Canonical scenario — Checkout Failure After Pricing Schema Migration

- Source narrative: `fixtures/preferred_scenario_source.md` (preserved from the supplied fixture).
- Executable graph fixture: `fixtures/canonical_incident.json`.
- Hidden `ground_truth` is test-only metadata and is never seeded as `ROOT_CAUSE` or `SIMILAR_TO`.

### Canonical ground truth (test-only)

- **primary_root_cause:** Backward-incompatible schema migration during mixed-version rollout.
- **causal_chain:** ['MIG-203 made region_scope NOT NULL', 'Pricing API v4.1 still wrote NULL', 'database rejected v4.1 writes', 'v4.1 requests failed', 'Checkout requests routed to v4.1 failed', 'retry traffic increased', 'Pricing Database CPU rose']
- **contributing_failure:** Required compatibility testing was skipped.
- **secondary_consequence:** Retry storm caused database saturation; high CPU was not the initiating cause.
- **ownership_gap:** SYS-LEGACY-PROMO has no current owner after TEAM-GROWTH dissolved on 2026-07-01.
- **commitment_breach:** COM-017 is violated if v4.1 compatibility breaks during DPL-882.
- **policy_drift:** Actual path skipped compatibility testing and downstream verification.
- **structural_precedent:** INC-074 has the same old-consumer/new-schema incompatibility motif despite different vocabulary.
- **expected_potential_blast_radius:** ['SYS-CHECKOUT', 'SYS-MOBILE-OFFERS', 'SYS-LEGACY-PROMO', 'SYS-PRICING-ANALYTICS']
- **observed_impact_initially:** ['SYS-CHECKOUT']

## Supporting scenarios

### SCN-AGENT-001 — Agent Coordination Deadlock and Handoff
- **Purpose:** Supports deadlock, handoff contract, governed action and exactly-once foundations.
- **Explicit ground truth:** deadlock_cycle=['TASK-A', 'TASK-B', 'TASK-A']; handoff_invalid_because=evidence_ids missing; exactly_once_key=restart:SYS-PRICING-API:INC-001

### SCN-ANOM-001 — Shadow Production Dependency
- **Purpose:** Supports graph anomaly and motif-deviation detection.
- **Explicit ground truth:** anomalous_edge=['SYS-ANALYTICS-UI', 'DEPENDS_ON', 'SYS-PROD-ORDERS-DB']; reason=UI bypasses normal API mediation motif.

### SCN-BRIDGE-001 — Single Cross-Team Release Bridge
- **Purpose:** Supports organizational bottleneck / bridge detection.
- **Explicit ground truth:** bridge_person=PERSON-DEV; removal_effect=Platform loses its only modeled path to Security release review.

### SCN-BUS-001 — Single Expert for Ledger Export
- **Purpose:** Supports organizational bus-factor analysis.
- **Explicit ground truth:** bus_factor=1; critical_entity=SYS-LEDGER-EXPORT; only_expert=PERSON-ISHA; no_backup_expert=True

### SCN-COMMIT-001 — Overdue Data Export Commitment
- **Purpose:** Supports commitment and obligation tracking.
- **Explicit ground truth:** at_time=2026-10-16T01:00:00+05:30; is_overdue=True; satisfaction_event_exists=False

### SCN-DUP-001 — Duplicate Refund Automation Initiatives
- **Purpose:** Supports duplicate-work / initiative collision detection.
- **Explicit ground truth:** duplicate_pair=['PROJ-REFUND-A', 'PROJ-REFUND-B']; reason=same goal and same core system dependency under different teams

### SCN-IDENTITY-001 — Ambiguous Source Identity
- **Purpose:** Supports relational entity resolution without premature canonical merge.
- **Explicit ground truth:** accepted_mapping=['SRCREC-HR-991', 'PERSON-RIYA']; unresolved_candidate=['SRCREC-CRM-42', 'PERSON-RIYA']; must_not_auto_merge=True
