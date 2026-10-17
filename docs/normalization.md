# Phase 9 Normalization

Adapters produce source-shaped records; normalizers map them to existing ontology candidates. There are no canonical `GitHubPerson`, `JiraPerson` or `SlackPerson` labels.

Examples:

- GitHub user -> `Person` identity candidate; repository -> `System`; pull request -> `Change`; author/reviewer relationships -> existing people and provenance.
- Jira issue -> `Task`; project -> `Project`; assignee -> `Person`; component/team/system links -> existing relationships.
- Slack/Teams message -> `Document`/message artifact plus `UNVERIFIED` Claim candidate when a deterministic assertion mapping exists.
- Policy document -> `Document`, `Policy`, requirement `Action` candidates and structured `REQUIRES`/`GOVERNS` semantics.
- Telemetry -> `Event` and `Evidence`, retaining source event time and system/incident `ABOUT` links.
- service catalog/database/internal API -> `System`, `Team` and candidate `OWNS`/`DEPENDS_ON` facts subject to trust rules.

Unknown schema versions/record types yield warnings/quarantine rather than silent mappings. Mapping rule and version are persisted in provenance.
