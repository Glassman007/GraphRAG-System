# Phase 9 Source Adapters

All adapters implement the common `SourceAdapter` output contract. The common interface standardizes SourceRecords, health, cursor behavior and artifact references; it does not force providers to share fetching mechanics.

| Adapter | Implemented | Fixture verified | Live verified | Notes |
|---|---|---|---|---|
| GitHub | yes | yes | no | read-only organization/repository/PR shaped API boundary; env token/org |
| Jira | yes | yes | no | read-only issue/project/user shaped API boundary; env URL/user/token |
| Slack | yes | yes | no | read-only message/user shaped API boundary; token from env |
| Teams | contract | yes | no | Microsoft Graph-shaped boundary intentionally fixture-only here |
| Documents | yes | yes | no | generalized Markdown/text/HTML/PDF-reference/wiki/policy record contract |
| Telemetry | yes | yes | no | logs/metrics/traces/alerts/deployment-health observations |
| Database | yes | yes | no | configured read-only query abstraction; optional PostgreSQL/psycopg live backend |
| Internal API | yes | yes | no | server-configured JSON/REST GET endpoints; no user-supplied URL |

Credentials are obtained only from environment/server configuration. They are excluded from `SourceConfig.public_dict()`, graph persistence and API responses.
