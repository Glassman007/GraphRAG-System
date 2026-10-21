"""Bounded, tenant-scoped reads of persisted SQL schema facts for Company Brain."""
from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.temporal import public_properties


def _properties(value: Any) -> dict[str, Any]:
    return public_properties(value.properties)


class CompanyBrainSchemaService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def list_tables(self, *, source_id: str | None = None, limit: int = 200) -> dict[str, Any]:
        limit = max(1, min(limit, 200))
        params = {"tenant_id": self.client.settings.tenant_id, "source_id": source_id}
        rows = self.client.read(
            "MATCH (t:Entity:SqlTable {tenant_id:$tenant_id}) "
            "WHERE ($source_id IS NULL OR t.source_ref_id = $source_id) "
            f"RETURN t ORDER BY t.name, t.id LIMIT {limit + 1}", params,
        ).result_set
        tables = [_properties(row[0]) for row in rows[:limit]]
        ids = [table["id"] for table in tables]
        foreign_keys = []
        if ids:
            edges = self.client.read(
                "MATCH (a:Entity:SqlTable {tenant_id:$tenant_id})-[r:FOREIGN_KEY_TO]->"
                "(b:Entity:SqlTable {tenant_id:$tenant_id}) "
                "WHERE a.id IN $ids AND b.id IN $ids "
                "RETURN a.id, r, b.id ORDER BY a.id, r.constraint_name, b.id",
                {"tenant_id": self.client.settings.tenant_id, "ids": ids},
            ).result_set
            foreign_keys = [{"source_id": row[0], "target_id": row[2], "properties": _properties(row[1])}
                            for row in edges]
        return {"tables": tables, "foreign_keys": foreign_keys, "truncated": len(rows) > limit}

    def table_detail(self, table_id: str) -> dict[str, Any] | None:
        params = {"tenant_id": self.client.settings.tenant_id, "id": table_id}
        rows = self.client.read(
            "MATCH (t:Entity:SqlTable {tenant_id:$tenant_id, id:$id}) RETURN t LIMIT 1", params,
        ).result_set
        if not rows:
            return None
        table = _properties(rows[0][0])
        columns = [_properties(row[0]) for row in self.client.read(
            "MATCH (t:Entity:SqlTable {tenant_id:$tenant_id, id:$id})-[:HAS_COLUMN]->"
            "(c:Entity:SqlColumn {tenant_id:$tenant_id}) RETURN c ORDER BY c.column_name", params,
        ).result_set]
        constraints = [_properties(row[0]) for row in self.client.read(
            "MATCH (t:Entity:SqlTable {tenant_id:$tenant_id, id:$id})-[:HAS_CONSTRAINT]->"
            "(c:Entity:SqlConstraint {tenant_id:$tenant_id}) RETURN c ORDER BY c.name", params,
        ).result_set]
        connections = [{"source": _properties(row[0]), "target": _properties(row[2]),
                        "properties": _properties(row[1])} for row in self.client.read(
            "MATCH (a:Entity:SqlTable {tenant_id:$tenant_id})-[r:FOREIGN_KEY_TO]->"
            "(b:Entity:SqlTable {tenant_id:$tenant_id}) "
            "WHERE a.id = $id OR b.id = $id "
            "RETURN a, r, b ORDER BY a.name, r.constraint_name, b.name", params,
        ).result_set]
        source_rows = self.client.read(
            "MATCH (d:Entity:Document {tenant_id:$tenant_id})-[:DEFINES]->"
            "(t:Entity:SqlTable {tenant_id:$tenant_id, id:$id}) "
            "OPTIONAL MATCH (repo:Entity:System {tenant_id:$tenant_id})-[:CONTAINS]->(d) "
            "RETURN d, repo ORDER BY d.id LIMIT 1", params,
        ).result_set
        source = ({"file": _properties(source_rows[0][0]),
                   "repository": _properties(source_rows[0][1]) if source_rows[0][1] else None}
                  if source_rows else None)
        return {"table": table, "columns": columns, "constraints": constraints,
                "foreign_keys": connections, "source": source}
