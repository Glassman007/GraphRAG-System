# Retrieval Routing

`RetrievalPlanner` returns explicit modes plus a reason for every chosen retriever.

Deterministic rules:
- **LEXICAL:** identifiers, exact phrases, filenames, policy wording, stack/error text;
- **VECTOR:** conceptual/causal/similarity/historical questions;
- **DOCUMENT:** FalkorDB already selected Artifact/Document candidates;
- **METADATA:** author/source/status/time/repository-type questions;
- **SQL:** graph scope contains a configured `database` DataSource;
- **API:** graph scope contains a configured `internal_api` DataSource.

SQL/API modes do not accept arbitrary SQL or URLs. The default provider reads graph-linked Phase 9 SourceRecords for selected configured sources. Production query-template/provider callbacks can be substituted without changing the planner contract.

Hybrid lexical/vector results use Reciprocal Rank Fusion (RRF, k=60), then a tiny deterministic tie-break from graph distance and source authority. Retrieval relevance remains dominant, and lower-authority contradictory evidence is never filtered solely because of authority.

## Configured SQL/API refresh

SQL/API retrieval is graph-selected first. By default it reads graph-linked Phase 9 SourceRecords. If `metadata_filters.refresh_external=true`, only the server-configured Phase 9 adapter for the selected DataSource may perform a fresh read. Database adapters execute only their configured read-only query template; internal API adapters use only configured hosts/paths. Retrieval requests cannot supply SQL, URLs, or credentials.
