# Phase 9 Ingestion Security

- adapters are read-only by default;
- provider credentials come from environment/server-side secret configuration and are redacted from serialized source configuration;
- no public endpoint accepts arbitrary SQL;
- no public endpoint accepts an arbitrary external URL;
- Internal API hosts/endpoints are server configured;
- database ingestion uses configured parameterized/read-only query definitions;
- adapter pages and pipeline batches are bounded;
- default tests never make live provider calls;
- data minimization favors organizational IDs, work email/name/team context and omits unrelated personal metadata;
- tenant_id is preserved on ingestion metadata and all graph writes through the existing client.
