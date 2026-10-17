# Phase 9 Source Trust

Phase 9 answers **what an external source reported**; Phase 7 remains responsible for **what the organization may trust/promote/supersede**.

Trust classes are configured per DataSource, including authoritative domains. They are not globally hardcoded by provider brand.

Examples in the default fixture registry:

- Slack/Teams: untrusted assertion sources; claims stay unverified.
- GitHub/Jira/telemetry: evidence-bearing but not automatically formal ownership authority.
- document policy source: authoritative for configured policy semantics.
- database/service catalog source: authoritative evidence, but automatic structural promotion disabled by default.
- configured internal service catalog API: authoritative with explicit automatic ownership/dependency validation enabled for the demo.

For formal ownership/responsibility, an authoritative source with auto-validation enabled routes through existing Phase 7 responsibility promotion. When auto-validation is disabled, the source produces Evidence + an UNVERIFIED structural Claim. Conflicting structural Claims for the same predicate/target and different actors are connected with `CONTRADICTS`, preserving disagreement for the existing Company Brain.
