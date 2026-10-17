# Source Credentials

Secrets never live in FalkorDB. The graph stores only an opaque `credential_ref`, provider name and configured/not-configured metadata.

`CredentialStore` supports `put`, `delete`, `exists`, `metadata`, and `resolve_for_connector`. The local development implementation stores server-side files outside the graph and applies restrictive filesystem permissions where supported. The abstraction is designed for future Vault/AWS/Azure/GCP implementations.

GET APIs never echo credential values. Source configuration redacts token/password/secret/DSN/private-key style fields. Live databases use server-registered read-only views; live internal APIs use server-registered endpoints; supported external connector base URLs are HTTPS and allowlisted.
