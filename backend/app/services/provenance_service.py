from __future__ import annotations

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.temporal import public_properties


class ProvenanceService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _node(value):
        if isinstance(value, dict):
            return public_properties(value)
        return public_properties(value.properties) if hasattr(value, "properties") else value

    def get_entity_provenance(self, entity_id: str) -> dict:
        result = self.client.read(
            """
            MATCH (n:Entity {tenant_id:$tenant_id, id:$id})
            OPTIONAL MATCH (n)-[:DERIVED_FROM]->(s:Entity {tenant_id:$tenant_id})
            OPTIONAL MATCH (e:Entity:Evidence {tenant_id:$tenant_id})-[:SUPPORTS|REFUTES]->(n)
            RETURN n, collect(DISTINCT s) AS sources, collect(DISTINCT e) AS evidence
            """,
            {"tenant_id": self.client.settings.tenant_id, "id": entity_id},
        )
        if not result.result_set:
            return {"entity": None, "sources": [], "evidence": []}
        n, sources, evidence = result.result_set[0]
        return {
            "entity": self._node(n),
            "sources": [self._node(x) for x in sources if x is not None],
            "evidence": [self._node(x) for x in evidence if x is not None],
        }

    def get_relationship_provenance(self, source_id: str, rel_type: str, target_id: str) -> list[dict]:
        from backend.app.graph.schema import validate_relationship
        rel_type = validate_relationship(rel_type)
        result = self.client.read(
            f"""
            MATCH (a:Entity {{tenant_id:$tenant_id, id:$source_id}})-[r:{rel_type}]->
                  (b:Entity {{tenant_id:$tenant_id, id:$target_id}})
            OPTIONAL MATCH (s:Entity {{tenant_id:$tenant_id}})
            WHERE s.id = r.source_ref_id
            RETURN r.edge_id, r.source_ref_id, r.confidence, r.valid_from, r.valid_until, s
            """,
            {"tenant_id": self.client.settings.tenant_id, "source_id": source_id, "target_id": target_id},
        )
        rows=[]
        for edge_id, source_ref_id, confidence, valid_from, valid_until, source in result.result_set:
            rows.append({
                "edge_id": edge_id,
                "source_ref_id": source_ref_id,
                "confidence": confidence,
                "valid_from": valid_from,
                "valid_until": valid_until,
                "source": self._node(source) if source else None,
            })
        return rows
