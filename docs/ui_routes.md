# Phase 12 UI Routes

- `/situations`
- `/situations/:situationId`
- `/investigations`
- `/investigations/:investigationId`
- `/work`
- `/plans/:planId`
- `/knowledge`
- `/claims/:claimId`
- `/evidence/:evidenceId`
- `/decisions`
- `/decisions/:decisionId`
- `/entities`
- `/entities/:entityId`
- `/simulations`
- `/company-brain`
- `/anomalies`

Query parameters are used for reproducible tabs and temporal/filter state, for example:

- `/company-brain?tab=bus-factor`
- `/entities/SYS-PRICING-API?tab=blast-radius&depth=3`
- `/situations/INC-001?tab=timeline&as_of=...`
