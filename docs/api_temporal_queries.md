# External API Temporal Semantics

Where the underlying capability is temporal, `/api/v1` accepts `as_of` and delegates to the existing epoch-based temporal model.

Examples include entity reads, entity history, paths, blast radius, process reconstruction/policy drift, risks, and retrieval context.

Historical requests must not use relationships or facts that became valid after the requested time. The API does not perform lexical timestamp comparison and does not replace existing Phase 7/8/10 temporal logic with route-local rules.
