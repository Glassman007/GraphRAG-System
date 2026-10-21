"""Verify the pinned Neon SQL artifact through a disposable FalkorDB graph.

Run from project root with Stage 3 dependencies installed:
  python -m scripts.verify_neon_sql_stage3 --output reports/verinex_neon_integration/STAGE_3_REMOTE.json
The generated graph is left intact for inspection; no existing graph is reset.
"""
from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path

from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.schema import apply_schema
from backend.app.ingestion.adapters.github import GitHubAdapter
from backend.app.ingestion.artifacts.local import LocalArtifactStore
from backend.app.ingestion.models import SourceConfig
from backend.app.ingestion.normalization.postgres_schema import extract_postgres_schema
from backend.app.ingestion.pipeline import IngestionPipeline
from backend.app.ingestion.registry import SourceRegistry

COMMIT = "b54cb67534bf20775803b181b7a1c6f573422161"
REPO = "neondatabase/postgres-sample-dbs"


def _rows(client, query, tenant):
    return client.read(query, {"tenant_id": tenant}).result_set


def _counts(client, tenant):
    result = {}
    for label in ("SqlTable", "SqlColumn", "SqlConstraint", "SourceRecord", "Artifact", "IngestionRun"):
        result[label] = int(_rows(client, f"MATCH (n:{label} {{tenant_id:$tenant_id}}) RETURN count(n)", tenant)[0][0])
    for rel in ("FOREIGN_KEY_TO", "DEFINES", "HAS_COLUMN", "HAS_CONSTRAINT"):
        result[rel] = int(_rows(client, f"MATCH (a:Entity {{tenant_id:$tenant_id}})-[r:{rel}]->(b:Entity {{tenant_id:$tenant_id}}) RETURN count(r)", tenant)[0][0])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", default="verinex_neon_stage3_" + uuid.uuid4().hex[:8])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    tenant = "neon-stage3"
    settings = Settings(falkordb_host=os.getenv("FALKORDB_HOST", "localhost"),
                        falkordb_port=int(os.getenv("FALKORDB_PORT", "6379")),
                        falkordb_password=os.getenv("FALKORDB_PASSWORD") or None,
                        falkordb_graph=args.graph, tenant_id=tenant)
    client = FalkorGraphClient(settings)
    client.health_check()
    apply_schema(client)
    config = SourceConfig(id="SRC-NEON-STAGE3", source_type="github", name="Neon SQL schema",
                          source_instance="neon-stage3", base_url="https://api.github.com",
                          settings={"repository": REPO, "ref": COMMIT, "files": ["dvdrental.sql"], "anonymous": True})
    fetched = GitHubAdapter(config).fetch(limit=2)
    file = next(r for r in fetched.records if r.record_type == "sql_file")
    parsed = extract_postgres_schema(file.artifacts[0].content)
    registry = SourceRegistry(client)
    registry.register(config)
    artifact_root = Path(os.getenv("VERINEX_NEON_STAGE3_ARTIFACT_ROOT") or Path(os.getenv("TEMP", ".")) / "verinex-neon-stage3-artifacts" / args.graph)
    pipeline = IngestionPipeline(client, registry=registry, artifact_store=LocalArtifactStore(artifact_root))
    reports = []
    counts = []
    for _ in range(2):
        report = pipeline.sync(config.id, mode="full", max_records=2, batch_size=1)
        reports.append({"status": report.status.value, "fetched": report.fetched,
                        "normalized": report.normalized, "written": report.written,
                        "quarantined": report.quarantined, "failed": report.failed,
                        "artifacts": report.artifacts, "warnings": report.warnings,
                        "run_id": report.run_id})
        if report.status.value != "SUCCEEDED" or report.quarantined or report.failed:
            raise AssertionError(f"Ingestion did not finish cleanly: {reports[-1]}")
        counts.append(_counts(client, tenant))
    if counts[0] != {**counts[1], "IngestionRun": counts[0]["IngestionRun"]}:
        raise AssertionError(f"Graph entity or edge counts changed on repeat: {counts}")
    if counts[1]["IngestionRun"] != counts[0]["IngestionRun"] + 1:
        raise AssertionError("Expected a new provenance run for the repeated ingestion")

    table_names = sorted(str(row[0]) for row in _rows(client,
        "MATCH (t:SqlTable {tenant_id:$tenant_id}) RETURN t.name ORDER BY t.name", tenant))
    foreign_keys = sorted((str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4])) for row in _rows(client,
        "MATCH (a:SqlTable {tenant_id:$tenant_id})-[r:FOREIGN_KEY_TO]->(b:SqlTable {tenant_id:$tenant_id}) "
        "RETURN a.name, r.constraint_name, b.name, r.source_commit_sha, r.source_file_hash", tenant))
    expected_fks = sorted((name, c.name, c.referenced_table, COMMIT, file.raw_metadata["sha256"])
                          for name, c in parsed.foreign_keys)
    assert table_names == sorted(parsed.tables)
    assert foreign_keys == expected_fks
    assert len(table_names) == 15 and len(foreign_keys) == len(parsed.foreign_keys)
    assert counts[0]["SqlColumn"] == sum(len(t.columns) for t in parsed.tables.values())
    assert counts[0]["SqlConstraint"] == sum(len(t.constraints) for t in parsed.tables.values())
    assert counts[0]["Artifact"] == 1 and counts[0]["SourceRecord"] == 2

    schema_chain = _rows(client,
        "MATCH (repo:System {tenant_id:$tenant_id})-[:CONTAINS]->(file:Document {tenant_id:$tenant_id})"
        "-[:DEFINES]->(table:SqlTable {tenant_id:$tenant_id, name:'public.payment'}) "
        "RETURN repo.name, file.name, table.name", tenant)
    assert schema_chain and [str(x) for x in schema_chain[0]] == [REPO, "dvdrental.sql", "public.payment"]
    lineage = _rows(client,
        "MATCH (a:SqlTable {tenant_id:$tenant_id})-[r:FOREIGN_KEY_TO]->(b:SqlTable {tenant_id:$tenant_id}) "
        "RETURN r.source_record_id, r.source_commit_sha, r.source_blob_sha, r.source_file_hash, r.ingestion_run_id", tenant)
    file_source = _rows(client,
        "MATCH (s:SourceRecord {tenant_id:$tenant_id, record_type:'sql_file'}) RETURN s.id", tenant)
    assert len(file_source) == 1 and len(lineage) == len(parsed.foreign_keys)
    assert all([str(x) for x in row] == [str(file_source[0][0]), COMMIT, file.raw_metadata["blob_sha"],
                                        file.raw_metadata["sha256"], reports[-1]["run_id"]] for row in lineage)
    artifact_lineage = _rows(client,
        "MATCH (file:Document {tenant_id:$tenant_id})-[:DERIVED_FROM]->(artifact:Artifact {tenant_id:$tenant_id}) "
        "RETURN file.name, artifact.sha256", tenant)
    assert artifact_lineage and [str(x) for x in artifact_lineage[0]] == ["dvdrental.sql", file.raw_metadata["sha256"]]

    path_query = (
        "MATCH (p:SqlTable {tenant_id:$tenant_id, name:'public.payment'})-[fk1:FOREIGN_KEY_TO]->"
        "(r:SqlTable {tenant_id:$tenant_id, name:'public.rental'})-[fk2:FOREIGN_KEY_TO]->"
        "(i:SqlTable {tenant_id:$tenant_id, name:'public.inventory'})-[fk3:FOREIGN_KEY_TO]->"
        "(f:SqlTable {tenant_id:$tenant_id, name:'public.film'}) "
        "RETURN p.name, fk1.constraint_name, r.name, fk2.constraint_name, i.name, fk3.constraint_name, f.name"
    )
    path_rows = _rows(client, path_query, tenant)
    assert path_rows, "Payment-to-film FK path absent in FalkorDB"
    path = [str(value) for value in path_rows[0]]
    assert path[1::2] == ["payment_rental_id_fkey", "rental_inventory_id_fkey", "inventory_film_id_fkey"]
    evidence = {"status": "PASS", "graph": args.graph, "tenant": tenant,
                "source_repository": REPO, "source_path": file.raw_metadata["path"],
                "source_commit_sha": COMMIT, "source_blob_sha": file.raw_metadata["blob_sha"],
                "source_file_hash": file.raw_metadata["sha256"], "artifact_root": str(artifact_root),
                "parsed": {"tables": len(parsed.tables), "columns": sum(len(t.columns) for t in parsed.tables.values()),
                           "primary_keys": sum(c.kind == "PRIMARY_KEY" for t in parsed.tables.values() for c in t.constraints),
                           "foreign_keys": len(parsed.foreign_keys), "warnings": parsed.warnings},
                "ingestion_runs": reports, "counts_after_each_run": counts,
                "repository_file_table_chain": [str(x) for x in schema_chain[0]],
                "foreign_key_provenance_verified": len(lineage),
                "artifact_lineage": [str(x) for x in artifact_lineage[0]],
                "tables": table_names,
                "foreign_keys": [{"from": a, "constraint": c, "to": b} for a, c, b, _, _ in foreign_keys],
                "path_cypher": path_query, "path_result": path}
    rendered = json.dumps(evidence, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
