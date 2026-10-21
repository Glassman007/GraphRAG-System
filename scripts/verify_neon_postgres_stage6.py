"""Build an isolated DVD schema database and verify live Sources-to-Company-Brain ingestion.

The verified local artifact supplies fixture DDL only; VERINEX reads pg_catalog from
the running database with a separate read-only account. No COPY rows are executed.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import time
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient
from backend.app.ingestion.normalization.postgres_schema import extract_postgres_schema
from backend.app.main import app


def docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def fixture():
    evidence = json.loads(Path("reports/verinex_neon_integration/STAGE_3_REMOTE.json").read_text(encoding="utf-8"))
    digest = evidence["source_file_hash"]
    path = Path(evidence["artifact_root"]) / "neon-stage3" / "github" / digest[:2] / digest / "payload.bin"
    data = path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest
    schema = extract_postgres_schema(data)
    assert not schema.warnings
    return schema


def create_fixture(admin_dsn: str, schema) -> None:
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TYPE public.mpaa_rating AS ENUM ('G','PG','PG-13','R','NC-17')")
            cur.execute("CREATE DOMAIN public.year AS integer")
            for table in schema.tables.values():
                columns = [sql.SQL("{} {}{}").format(sql.Identifier(c.name), sql.SQL(c.data_type),
                            sql.SQL(" NOT NULL" if c.not_null else "")) for c in table.columns.values()]
                cur.execute(sql.SQL("CREATE TABLE {}.{} ({})").format(
                    sql.Identifier(table.schema), sql.Identifier(table.name), sql.SQL(", ").join(columns)))
            for kind in ("PRIMARY_KEY", "FOREIGN_KEY"):
                for table in schema.tables.values():
                    for constraint in table.constraints:
                        if constraint.kind != kind:
                            continue
                        name = sql.Identifier(constraint.name)
                        columns = sql.SQL(", ").join(sql.Identifier(c) for c in constraint.columns)
                        if constraint.kind == "PRIMARY_KEY":
                            clause = sql.SQL("PRIMARY KEY ({})").format(columns)
                        else:
                            target_schema, target_name = constraint.referenced_table.split(".", 1)
                            target_columns = sql.SQL(", ").join(sql.Identifier(c) for c in constraint.referenced_columns)
                            clause = sql.SQL("FOREIGN KEY ({}) REFERENCES {}.{} ({})").format(
                                columns, sql.Identifier(target_schema), sql.Identifier(target_name), target_columns)
                        cur.execute(sql.SQL("ALTER TABLE {}.{} ADD CONSTRAINT {} {}").format(
                            sql.Identifier(table.schema), sql.Identifier(table.name), name, clause))


def main() -> int:
    parsed = fixture()
    suffix = uuid.uuid4().hex[:8]
    container = f"verinex-stage6-postgres-{suffix}"
    graph, tenant, source_id = f"verinex_neon_stage6_{suffix}", f"neon-stage6-{suffix}", f"SRC-NEON-STAGE6-{suffix.upper()}"
    admin_password, reader_password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    os.environ["POSTGRES_PASSWORD"] = admin_password
    try:
        docker("run", "-d", "--rm", "--name", container, "-e", "POSTGRES_PASSWORD",
               "-p", "127.0.0.1::5432", "postgres:16-alpine")
        port = int(docker("port", container, "5432/tcp").rsplit(":", 1)[1])
        admin_dsn = psycopg.conninfo.make_conninfo(host="127.0.0.1", port=port,
                                                    user="postgres", password=admin_password, dbname="postgres")
        for _ in range(40):
            try:
                with psycopg.connect(admin_dsn, connect_timeout=1) as conn:
                    break
            except psycopg.OperationalError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become available")
        with psycopg.connect(admin_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("CREATE DATABASE dvd_stage6")
        db_dsn = psycopg.conninfo.make_conninfo(admin_dsn, dbname="dvd_stage6")
        create_fixture(db_dsn, parsed)
        with psycopg.connect(db_dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier("verinex_reader"), sql.Literal(reader_password)))
            cur.execute("GRANT CONNECT ON DATABASE dvd_stage6 TO verinex_reader")
            cur.execute("GRANT USAGE ON SCHEMA public TO verinex_reader")
            cur.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO verinex_reader")
        reader_dsn = psycopg.conninfo.make_conninfo(host="127.0.0.1", port=port,
                                                     user="verinex_reader", password=reader_password,
                                                     dbname="dvd_stage6")
        os.environ.update({"VERINEX_STAGE6_DSN": reader_dsn, "FALKORDB_GRAPH": graph,
                           "GRAPH_HACKS_REGISTERED_DATABASE_SCHEMAS_JSON": json.dumps({
                               "dvd_stage6": {"dsn_env": "VERINEX_STAGE6_DSN", "schemas": ["public"]}}),
                           "GRAPH_HACKS_API_PRINCIPALS_JSON": json.dumps({
                               "stage6-local-admin": {"subject": "stage6-verifier", "tenant_id": tenant,
                                                      "permissions": ["ADMIN"]}})})
        headers = {"Authorization": "Bearer stage6-local-admin", "X-Tenant-ID": tenant}
        with psycopg.connect(reader_dsn) as conn, conn.cursor() as cur:
            cur.execute("SELECT current_user, has_schema_privilege(current_user,'public','CREATE')")
            account, can_create = cur.fetchone()
            assert account == "verinex_reader" and not can_create
            cur.execute("SELECT count(*) FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind='r'")
            db_tables = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM pg_catalog.pg_constraint con JOIN pg_catalog.pg_class c ON c.oid=con.conrelid JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND con.contype='f'")
            db_fks = cur.fetchone()[0]
        with TestClient(app) as api:
            created = api.post("/api/v1/sources", headers=headers, json={
                "source_id": source_id, "display_name": "DVD rental PostgreSQL catalog",
                "connector_type": "database", "connection_mode": "live",
                "connection_config": {"registered_schema": "dvd_stage6"}})
            assert created.status_code == 201, created.text
            health = api.post(f"/api/v1/sources/{source_id}/test", headers=headers)
            assert health.status_code == 200, health.text
            assert health.json()["status"] == "HEALTHY" and health.json()["live"]
            runs = []
            for _ in range(2):
                response = api.post(f"/api/v1/sources/{source_id}/sync", headers=headers,
                                    json={"mode": "full", "max_records": 1})
                assert response.status_code == 200, response.text
                run = response.json()
                runs.append({k: run[k] for k in ("status", "fetched", "normalized", "written", "quarantined", "failed")})
                assert run["status"] == "SUCCEEDED" and run["failed"] == run["quarantined"] == 0
                response = api.get("/api/v1/company-brain/sql-schema", headers=headers,
                                   params={"source_id": source_id})
                assert response.status_code == 200, response.text
                graph_data = response.json()
                assert len(graph_data["tables"]) == db_tables == len(parsed.tables) == 15
                assert len(graph_data["foreign_keys"]) == db_fks == len(parsed.foreign_keys) == 18
            by_name = {table["name"]: table for table in graph_data["tables"]}
            chain = [f"public.{name}" for name in ("payment", "rental", "inventory", "film")]
            actual_fks = {(by_name_name, edge["properties"]["constraint_name"], target_name)
                          for edge in graph_data["foreign_keys"]
                          for by_name_name, node in by_name.items() if node["id"] == edge["source_id"]
                          for target_name, target in by_name.items() if target["id"] == edge["target_id"]}
            expected_fks = {(name, c.name, c.referenced_table) for name, c in parsed.foreign_keys}
            assert actual_fks == expected_fks
            for left, right in zip(chain, chain[1:]):
                assert any(a == left and b == right for a, _, b in actual_fks)
            detail = api.get(f"/api/v1/company-brain/sql-schema/{by_name['public.payment']['id']}", headers=headers)
            assert detail.status_code == 200, detail.text
            payment = detail.json()
            assert payment["source"]["file"]["source_database"] == "dvd_stage6"
            assert payment["source"]["repository"]["system_type"] == "postgresql_database"
            assert any(c["constraint_name"] == "payment_rental_id_fkey" for c in payment["constraints"])
            state = api.get(f"/api/v1/sources/{source_id}", headers=headers).json()
            assert state["ingestion"]["status"] == "SUCCESS"
        client = FalkorGraphClient(Settings(falkordb_graph=graph, tenant_id=tenant))
        counts = {}
        for label in ("SqlTable", "SqlColumn", "SqlConstraint"):
            counts[label] = client.read(f"MATCH (n:Entity:{label} {{tenant_id:$tenant_id}}) RETURN count(n)",
                                        {"tenant_id": tenant}).result_set[0][0]
        counts["FOREIGN_KEY_TO"] = client.read(
            "MATCH (a:Entity:SqlTable {tenant_id:$tenant_id})-[r:FOREIGN_KEY_TO]->(b:Entity:SqlTable {tenant_id:$tenant_id}) RETURN count(r)",
            {"tenant_id": tenant}).result_set[0][0]
        assert counts == {"SqlTable": 15, "SqlColumn": 86, "SqlConstraint": 33, "FOREIGN_KEY_TO": 18}
        cypher_path = client.read(
            "MATCH (p:Entity:SqlTable {tenant_id:$tenant_id, name:'public.payment'})-[:FOREIGN_KEY_TO]->"
            "(r:Entity:SqlTable {tenant_id:$tenant_id, name:'public.rental'})-[:FOREIGN_KEY_TO]->"
            "(i:Entity:SqlTable {tenant_id:$tenant_id, name:'public.inventory'})-[:FOREIGN_KEY_TO]->"
            "(f:Entity:SqlTable {tenant_id:$tenant_id, name:'public.film'}) "
            "RETURN p.name,r.name,i.name,f.name", {"tenant_id": tenant}).result_set
        assert cypher_path and list(cypher_path[0]) == chain
        stage5 = json.loads(Path("reports/verinex_neon_integration/STAGE_5_DOWNSTREAM.json").read_text(encoding="utf-8"))
        previous = FalkorGraphClient(Settings(falkordb_graph=stage5["graph"], tenant_id=stage5["tenant"]))
        previous_tables = {row[0] for row in previous.read(
            "MATCH (t:Entity:SqlTable {tenant_id:$tenant_id}) RETURN t.name",
            {"tenant_id": stage5["tenant"]}).result_set}
        previous_fks = {tuple(row) for row in previous.read(
            "MATCH (a:Entity:SqlTable {tenant_id:$tenant_id})-[r:FOREIGN_KEY_TO]->"
            "(b:Entity:SqlTable {tenant_id:$tenant_id}) RETURN a.name,r.constraint_name,b.name",
            {"tenant_id": stage5["tenant"]}).result_set}
        previous_ids = {row[0] for row in previous.read(
            "MATCH (t:Entity:SqlTable {tenant_id:$tenant_id}) RETURN t.id",
            {"tenant_id": stage5["tenant"]}).result_set}
        assert set(by_name) == previous_tables and actual_fks == previous_fks
        assert {t["id"] for t in graph_data["tables"]}.isdisjoint(previous_ids)
        print(json.dumps({"status": "PASS", "graph": graph, "tenant": tenant,
                          "source_id": source_id, "postgresql": "live_read_only", "catalog_tables": db_tables,
                          "catalog_foreign_keys": db_fks, "graph_counts_after_two_syncs": counts,
                          "runs": runs, "path": chain, "company_brain": "PASS",
                          "stage5_schema_match": True, "source_ids_distinct": True}, indent=2))
        return 0
    finally:
        if container in docker("ps", "-a", "--format", "{{.Names}}").splitlines():
            docker("stop", container)


if __name__ == "__main__":
    raise SystemExit(main())
