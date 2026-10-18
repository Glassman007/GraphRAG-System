Phase 1 Canonical Scenario
Scenario: Checkout Failure After Pricing Schema Migration
1. Fictional company
Company: Northstar Commerce
Northstar operates an e-commerce platform used by web and mobile customers.
The organization has several engineering teams that independently own interconnected production systems.
The relevant teams are:
- Payments Team
  - owns Checkout Service
  - owns Order Service
- Pricing Platform Team
  - owns Pricing API
  - owns Pricing Database
- SRE Team
  - operates monitoring and production incident infrastructure
- Growth Integrations Team
  - previously owned Legacy Promotion Adapter
  - team was dissolved three months ago
  - ownership of the adapter was never reassigned
2. Relevant people
Maya Rao
- Role: Payments Engineering Lead
- Team: Payments
- Owns Checkout Service
- Authorized to approve emergency Checkout changes
Arjun Mehta
- Role: Pricing Platform Lead
- Team: Pricing Platform
- Owns Pricing API
Riya Sen
- Role: Senior Database Engineer
- Team: Pricing Platform
- Primary expert on Pricing Database
- Previously resolved a related database compatibility incident
Kabir Shah
- Role: SRE On-Call Engineer
- Team: SRE
- First responder for the current incident
Neha Verma
- Role: Platform Engineer
- Team: Pricing Platform
- Created the database migration involved in the incident
3. Relevant production systems
Checkout Service
ID:
SYS-CHECKOUT

Owned by:
Payments Team

Responsibilities:
- checkout requests;
- cart pricing verification;
- order submission.
Depends on:
Pricing API
Order Service
Inventory Gateway

Pricing API
ID:
SYS-PRICING-API

Owned by:
Pricing Platform Team

Responsibilities:
- product prices;
- promotions;
- discounts;
- price validation.
Depends on:
Pricing Database

Pricing Database
ID:
SYS-PRICING-DB

Owned by:
Pricing Platform Team

Stores:
- pricing rules;
- promotions;
- discount rules;
- regional price configuration.
Order Service
ID:
SYS-ORDER

Owned by:
Payments Team

Depends indirectly on pricing information produced by Checkout.
Mobile Offers Service
ID:
SYS-MOBILE-OFFERS

Owned by:
Mobile Team

Also consumes:
Pricing API

It has not yet reported an outage.
Analytics Pricing Pipeline
ID:
SYS-PRICING-ANALYTICS

Consumes pricing data directly from:
Pricing Database

Runs every hour.
Legacy Promotion Adapter
ID:
SYS-LEGACY-PROMO

Consumes:
Pricing API

Its former owner was:
Growth Integrations Team

But that team has been dissolved.
It currently has no valid owner.
This is intentional.
4. Core dependency graph
The actual graph should eventually resemble:
Checkout
   │
   ├── DEPENDS_ON → Pricing API
   │                     │
   │                     └── DEPENDS_ON → Pricing Database
   │
   ├── DEPENDS_ON → Order Service
   │
   └── DEPENDS_ON → Inventory Gateway


Mobile Offers
      │
      └── DEPENDS_ON → Pricing API


Legacy Promotion Adapter
      │
      └── DEPENDS_ON → Pricing API


Pricing Analytics
      │
      └── DEPENDS_ON → Pricing Database

5. The change before the incident
At:
2026-10-16 14:03 IST

a production deployment occurs.
Deployment:
DPL-882

Created by:
Neha Verma

Approved by:
Arjun Mehta

Deployment contains database migration:
MIG-203

The migration modifies the table:
discount_rules

Before the migration:
region_scope

could contain:
NULL

A NULL value meant:
This discount applies globally.

Migration MIG-203 changes:
region_scope

to:
NOT NULL

and introduces:
GLOBAL

as the explicit value representing global discounts.
The newest Pricing API version understands this new representation.
However, older Pricing API instances are still running during the rolling deployment.
Those older instances still attempt to write:
NULL

for global promotions.
6. The incident
Incident:
INC-001

Title:
Checkout failures following Pricing Database migration
Incident begins:
2026-10-16 14:08 IST

Observed symptoms:
- Checkout error rate increases from approximately 0.4% to 18%.
- Pricing API begins returning intermittent HTTP 500 responses.
- Checkout latency increases dramatically.
- Pricing Database CPU usage rises.
- Retry traffic increases.
- Some checkout requests succeed while others fail.
Kabir, the SRE on-call engineer, opens the incident.
At this point nobody knows the root cause.
7. Important twist
Database CPU reaches approximately:
91%

shortly after the incident begins.
This creates a plausible alternative explanation:
The Pricing Database became overloaded and caused Pricing API failures.

However, the CPU spike does not begin until after Pricing API errors and retries have already increased.
The CPU spike is therefore mostly a consequence of the retry storm, not the original cause.
This distinction should not simply be handed to the future investigation agent.
It should have to discover it from timestamps and relationships.
8. Available evidence
Evidence E-001 — Deployment record
DPL-882
deployed_at = 14:03

Contains:
MIG-203
Pricing API v4.2 rollout

Source:
Deployment System

Evidence E-002 — Migration definition
Shows:
region_scope:
nullable = false

Source:
Git repository

Associated with:
MIG-203

Evidence E-003 — Pricing API logs
Beginning at:
14:08:14

older API instances report errors similar to:
constraint violation:
region_scope cannot be null

Source:
Logging system

Evidence E-004 — Database metrics
Database CPU:
14:03 → 48%
14:07 → 51%
14:08 → 58%
14:10 → 76%
14:12 → 91%

Source:
Monitoring system

Evidence E-005 — Request retry metrics
Pricing API retries begin increasing sharply at:
14:08

and continue increasing before the largest database CPU spike.
Source:
Monitoring system

Evidence E-006 — Checkout traces
Checkout failures occur primarily when requests reach Pricing API instances still running:
v4.1

Requests hitting:
v4.2

mostly succeed.
Source:
Distributed tracing system

Evidence E-007 — Arjun's initial incident message
Arjun writes:
The database looks saturated. This is probably a capacity issue.

This is an assertion, not authoritative truth.
Evidence E-008 — Riya's initial hypothesis
Riya writes:
This looks like a mixed-version schema compatibility issue.

Also an assertion.
Neither statement should overwrite the other.
9. Conflicting claims
The system should initially contain at least these competing claims.
Claim C-001
Pricing Database saturation caused INC-001.

Asserted by:
Arjun

Supported by:
high database CPU

Confidence initially:
0.55

Claim C-002
MIG-203 broke compatibility with Pricing API v4.1.

Asserted by:
Riya

Supported by:
migration timing
constraint errors
version-dependent failures

Confidence initially:
0.70

Relationship:
C-001 CONTRADICTS C-002

Neither should initially be represented as:
ROOT_CAUSE

10. Missing evidence
At incident start the following evidence is missing.
Knowledge Gap Q-001
Was the required backward-compatibility test executed before DPL-882?

Knowledge Gap Q-002
Are consumers other than Checkout affected by the schema migration?

Potential affected systems:
- Mobile Offers;
- Legacy Promotion Adapter;
- Analytics Pricing Pipeline.
Knowledge Gap Q-003
Which Pricing API versions were active between 14:03 and 14:15?

Knowledge Gap Q-004
Does Legacy Promotion Adapter still have a valid organizational owner?

Ground truth:
No.

But the future agent should discover this from organizational relationships.
11. Company policy
Policy:
POL-DB-04

Name:
Production Database Compatibility Policy
Policy states:
Any production schema change affecting an actively consumed field requires:
1. backward-compatibility test
2. owning-team approval
3. downstream consumer verification

For rolling deployments:
old and new application versions must both remain compatible
until the deployment is complete.

Emergency exceptions require:
Incident Commander approval

No emergency exception existed for DPL-882.
12. Policy problem
The deployment record contains:
Arjun approval ✓

but the expected compatibility-test artifact cannot initially be found.
Later investigation should establish:
Compatibility test was skipped.

Therefore the actual process was:
Code Change
→ Review
→ Approval
→ Deployment

while policy expected:
Code Change
→ Review
→ Compatibility Test
→ Downstream Verification
→ Approval
→ Deployment

This gives the system future material for policy-vs-practice analysis without inventing another unrelated scenario.
13. Organizational commitment
Three days before the deployment, Pricing Platform made this commitment to Payments:
COM-017

Statement:
Pricing API v4.1 compatibility will remain supported throughout the v4.2 rolling migration.

Promisor:
Pricing Platform Team

Recipient:
Payments Team

Associated system:
Pricing API

Associated deployment:
DPL-882

Status at incident start:
ACTIVE

If the migration breaks v4.1 compatibility, this commitment has been violated.
14. Previous historical incident
Historical incident:
INC-074

Occurred:
2026-06-11

System:
Inventory Gateway

The terminology was different.
The problem was:
Inventory schema migration
        ↓
changed field representation
        ↓
older Inventory Worker still running
        ↓
old worker could not process new representation
        ↓
partial production failures

Resolution:
introduce compatibility layer
rollback migration
redeploy consumers
perform staged migration

This historical incident does not contain the words:
Pricing
Checkout
region_scope
discount

But structurally it resembles INC-001.
This is intentional so future Structural Precedent Reasoning cannot succeed using basic keyword matching alone.
15. Ownership anomaly
Legacy Promotion Adapter previously belonged to:
Growth Integrations Team

The team was dissolved:
2026-07-01

No replacement OWNS relationship exists.
However, the adapter remains:
ACTIVE

and still consumes:
Pricing API

This creates an intentionally orphaned production dependency.
16. Hidden blast radius
At incident start, users mainly report Checkout failures.
But the schema change potentially affects:
Pricing Database
   ↓
Pricing API
   ├── Checkout
   ├── Mobile Offers
   └── Legacy Promotion Adapter

Pricing Database
   ↓
Analytics Pricing Pipeline

The system should therefore distinguish:
observed impact

from:
potential impact

Not every reachable node should automatically be labeled broken.
17. Actual ground truth
This section is for fixtures/tests only.
Future agents should not receive this section directly.
The true causal chain is:
MIG-203
    ↓
made region_scope NOT NULL
    ↓
Pricing API v4.1 still wrote NULL
    ↓
database rejected those writes
    ↓
v4.1 Pricing API requests failed
    ↓
Checkout requests routed to v4.1 failed
    ↓
clients/services retried
    ↓
retry traffic increased
    ↓
Pricing Database CPU rose

Therefore:
Primary root cause:
Backward-incompatible schema migration during mixed-version rollout.

Contributing failure:
Required compatibility testing was skipped.

Secondary consequence:
Retry storm caused database saturation.

The high CPU was therefore real, but it was not the initiating cause.
18. Correct immediate remediation
A valid remediation is:
1. stop rollout
2. restore schema compatibility
3. allow NULL or provide compatibility translation
4. verify Pricing API v4.1 and v4.2
5. monitor Checkout recovery
6. continue deployment only after compatibility verification

Later permanent remediation:
stage schema migration
↓
deploy compatibility-capable applications
↓
remove old versions
↓
enforce new schema constraint afterward

19. Expected final incident conclusion
After complete investigation, the graph should eventually be capable of representing:
INC-001
  ↓ ROOT_CAUSE
Claim C-final

with:
C-final
  ↓ SUPPORTED_BY
E-002
E-003
E-005
E-006

And:
C-001
Database saturation caused incident

should not simply disappear.
It should become something like:
C-001
  ↓ REFUTED_BY
Evidence

or

C-001
status = REJECTED

This preserves organizational memory.
20. What should be visible to future agents initially
Agents may receive:
- organization graph;
- system dependencies;
- incident symptoms;
- initial evidence;
- policies;
- people/teams;
- initial conflicting claims.
Agents should not initially receive:
- final root cause;
- final remediation;
- which claim is correct;
- explanation that CPU was secondary;
- missing compatibility-test result;
- all affected downstream systems;
- explicit historical-incident match.
Those are things they should discover.
21. What this scenario is meant to enable later
Without forcing every feature into the scenario, it naturally gives you foundations for:
Track 1
- relational investigation;
- decision genealogy;
- blast radius;
- knowledge gaps;
- structural precedent;
- planning;
- counterfactual reasoning;
- evidence acquisition.
Track 2
- shared incident work;
- task creation;
- specialist-agent coordination;
- verification handoffs;
- resumability;
- governed remediation;
- exactly-once actions.
Track 3
- conflicting claims;
- authority;
- ownership;
- expertise;
- process reconstruction;
- policy drift;
- commitments;
- orphaned resources.