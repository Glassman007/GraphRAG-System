# Identity Review

`/sources/identity-review` turns Phase 9 quarantine/entity-resolution uncertainty into a first-class workflow. Each item shows incoming identity, source, object type, top candidate, confidence and candidate reasons.

Supported actions are confirm suggested match, choose another canonical entity, create a canonical entity, or reject/leave unresolved. All mutations call backend entity-resolution services; the browser never creates `NORMALIZED_TO` edges itself. Resolution actions create audit events and retain reviewer/time context.
