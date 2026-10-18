# Phase 12 UI Permissions

The browser discovers the authenticated Principal through `GET /api/v1/session`. UI checks improve usability only; the backend remains authoritative.

| Permission | UI operations |
|---|---|
| `READ_GRAPH` | situations, entities, paths, claims, tasks, agents, decisions |
| `READ_EVIDENCE` | Evidence detail/provenance, GraphRAG retrieval |
| `READ_ORG_ANALYTICS` | Company Brain, simulations, anomalies |
| `CREATE_INVESTIGATION` | create investigation |
| `CREATE_PLAN` | generate plan |
| `CLAIM_TASK` | claim/start/resume task |
| `WRITE_FINDING` | checkpoint, revalidate Claim, invalidate Evidence |
| `PROPOSE_ACTION` | propose governed Action |
| `EXECUTE_ACTION` | execute governed Action |
| `ADMIN` | all operations |

Disabled/hidden controls do not replace server authorization. A 403 from the backend is surfaced through `ErrorPanel` with the stable API error code.
