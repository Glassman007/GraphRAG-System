from __future__ import annotations

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.schema import validate_relationship
from backend.app.graph.temporal import public_properties, to_epoch_us


class TemporalService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _node(value):
        if isinstance(value, dict):
            return public_properties(value)
        return public_properties(value.properties) if hasattr(value, "properties") else value

    def relationship_at(self, source_id: str, rel_type: str, target_id: str, as_of: str) -> list[dict]:
        rel_type = validate_relationship(rel_type)
        result = self.client.read(
            f"""
            MATCH (a:Entity {{tenant_id:$tenant_id, id:$source_id}})-[r:{rel_type}]->
                  (b:Entity {{tenant_id:$tenant_id, id:$target_id}})
            WHERE (r._ts_valid_from_us IS NULL OR r._ts_valid_from_us <= $as_of_us)
              AND (r._ts_valid_until_us IS NULL OR r._ts_valid_until_us > $as_of_us)
            RETURN r.edge_id, r.valid_from, r.valid_until, r.confidence
            """,
            {
                "tenant_id": self.client.settings.tenant_id,
                "source_id": source_id,
                "target_id": target_id,
                "as_of_us": to_epoch_us(as_of),
            },
        )
        return [
            {"edge_id": row[0], "valid_from": row[1], "valid_until": row[2], "confidence": row[3]}
            for row in result.result_set
        ]

    def incident_state_at(self, incident_id: str, as_of: str) -> dict:
        params = {
            "tenant_id": self.client.settings.tenant_id,
            "id": incident_id,
            "as_of_us": to_epoch_us(as_of),
        }
        claims = self.client.read(
            """
            MATCH (c:Entity:Claim {tenant_id:$tenant_id})-[:ABOUT]->(i:Entity:Incident {tenant_id:$tenant_id, id:$id})
            WHERE c._ts_created_at_us <= $as_of_us
            RETURN c ORDER BY c._ts_created_at_us, c.id
            """,
            params,
        )
        evidence = self.client.read(
            """
            MATCH (e:Entity:Evidence {tenant_id:$tenant_id})-[:ABOUT]->(i:Entity:Incident {tenant_id:$tenant_id, id:$id})
            WHERE e._ts_observed_at_us <= $as_of_us
            RETURN e ORDER BY e._ts_observed_at_us, e.id
            """,
            params,
        )
        events = self.client.read(
            """
            MATCH (ev:Entity:Event {tenant_id:$tenant_id})-[:ABOUT]->(i:Entity:Incident {tenant_id:$tenant_id, id:$id})
            WHERE ev._ts_occurred_at_us <= $as_of_us
            RETURN ev ORDER BY ev._ts_occurred_at_us, ev.id
            """,
            params,
        )
        return {
            "as_of": as_of,
            "claims": [self._node(r[0]) for r in claims.result_set],
            "evidence": [self._node(r[0]) for r in evidence.result_set],
            "events": [self._node(r[0]) for r in events.result_set],
        }

    def reconstruct_incident_timeline(self, incident_id: str) -> list[dict]:
        result = self.client.read(
            """
            MATCH (ev:Entity:Event {tenant_id:$tenant_id})-[:ABOUT]->(i:Entity:Incident {tenant_id:$tenant_id, id:$id})
            RETURN ev ORDER BY ev._ts_occurred_at_us, ev.id
            """,
            {"tenant_id": self.client.settings.tenant_id, "id": incident_id},
        )
        return [self._node(r[0]) for r in result.result_set]
