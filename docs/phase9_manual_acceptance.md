# Phase 9 Manual Acceptance

## Automated isolated runner

With FalkorDB available locally:

```powershell
python scripts/verify_phase9_ingestion.py
```

The script creates a unique temporary FalkorDB graph, never modifies `company_brain`, ingests fixture-backed GitHub/Jira/Slack/document/telemetry/internal-API sources, verifies identity collapse/provenance/artifacts, calls existing routing/investigation/blast-radius/policy-drift/process services, reingests to verify idempotency, simulates an authoritative owner update, checks Phase 7 temporal promotion, prints PASS/FAIL, and deletes its temporary graph.

## Swagger

Start:

```powershell
uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs`.

1. `GET /ingestion/sources`
2. `POST /ingestion/sources/DS-ING-GITHUB/sync` with `{ "mode":"full", "max_records":100, "dry_run":true }`
3. repeat with `dry_run:false`
4. sync `DS-ING-JIRA`, `DS-ING-SLACK`, `DS-ING-DOCS`, `DS-ING-TELEMETRY`, `DS-ING-INTERNAL`
5. inspect `GET /ingestion/runs/{run_id}`
6. inspect `GET /ingestion/quarantine`
7. inspect `GET /ingestion/artifacts/{artifact_id}`
8. rerun unchanged sources and verify no duplicate canonical state.

## FalkorDB Browser queries

```cypher
MATCH (s:Entity:DataSource {tenant_id:'northstar'}) RETURN s ORDER BY s.id;
```

```cypher
MATCH (r:Entity:IngestionRun {tenant_id:'northstar'})-[:INGESTED]->(sr:Entity:SourceRecord)
RETURN r.id, r.status, sr.id, sr.source_type, sr.external_id, sr.checksum ORDER BY r.started_at;
```

```cypher
MATCH (x:Entity:ExternalIdentity {tenant_id:'northstar'})-[:RESOLVES_TO]->(p:Entity:Person)
RETURN p.id, p.name, p.email, collect({source:x.source_type, external_id:x.external_id});
```

```cypher
MATCH (sr:Entity:SourceRecord {tenant_id:'northstar'})-[:NORMALIZED_TO]->(e:Entity)
RETURN sr.id, sr.source_type, sr.external_id, labels(e), e.id, e.name LIMIT 100;
```

```cypher
MATCH (a:Entity)-[r:OWNS|DEPENDS_ON]->(b:Entity)
WHERE a.tenant_id='northstar' AND r.source_record_ids_csv IS NOT NULL
RETURN a.id, type(r), b.id, r.source_ref_id, r.source_record_ids_csv, r.mapping_rule;
```

```cypher
MATCH (c:Entity:Claim {tenant_id:'northstar'})-[x:CONTRADICTS]-(other:Entity:Claim)
WHERE c.assertion_kind='external_structural_assertion'
RETURN c.id, c.statement, other.id, other.statement, x.reason;
```

```cypher
MATCH (e:Entity:Evidence {tenant_id:'northstar'})-[:DERIVED_FROM]->(a:Entity:Artifact)
RETURN e.id, a.id, a.uri, a.sha256, a.size_bytes, a.mime_type;
```

```cypher
MATCH (q:Entity:IngestionQuarantineRecord {tenant_id:'northstar'})
RETURN q.id, q.status, q.reason, q.source_record_id, q.candidates;
```

```cypher
MATCH (new:Entity:SourceRecord {tenant_id:'northstar'})-[:SUPERSEDES]->(old:Entity:SourceRecord)
RETURN new.source_key, old.id, old.checksum, new.id, new.checksum, old.observed_at, new.observed_at;
```
