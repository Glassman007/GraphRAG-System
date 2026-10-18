from __future__ import annotations

from typing import Any
from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.temporal import to_epoch_us


def _bounded_depth(value: int) -> int:
    if not isinstance(value, int) or value < 1 or value > 8:
        raise ValueError("max_depth must be an integer from 1 to 8")
    return value


def get_entity(client: FalkorGraphClient, entity_id: str):
    return client.read(
        "MATCH (n:Entity {tenant_id:$tenant_id, id:$id}) RETURN n LIMIT 1",
        {"tenant_id": client.settings.tenant_id, "id": entity_id},
    )


def get_neighbors(client: FalkorGraphClient, entity_id: str):
    return client.read(
        """
        MATCH (n:Entity {tenant_id:$tenant_id, id:$id})-[r]-(m:Entity {tenant_id:$tenant_id})
        RETURN type(r), r, m
        ORDER BY type(r), m.id
        """,
        {"tenant_id": client.settings.tenant_id, "id": entity_id},
    )


def find_paths(client: FalkorGraphClient, source_id: str, target_id: str, max_depth: int = 4, limit: int = 20):
    depth = _bounded_depth(max_depth)
    limit = max(1, min(int(limit), 100))
    return client.read(
        f"""
        MATCH p=(a:Entity {{tenant_id:$tenant_id, id:$source_id}})-[*1..{depth}]-(b:Entity {{tenant_id:$tenant_id, id:$target_id}})
        RETURN p LIMIT {limit}
        """,
        {"tenant_id": client.settings.tenant_id, "source_id": source_id, "target_id": target_id},
    )


def get_dependencies(client: FalkorGraphClient, entity_id: str, max_depth: int = 4):
    depth = _bounded_depth(max_depth)
    return client.read(
        f"""
        MATCH p=(n:Entity {{tenant_id:$tenant_id, id:$id}})-[:DEPENDS_ON*1..{depth}]->(d:Entity {{tenant_id:$tenant_id}})
        RETURN DISTINCT d, length(p) AS depth
        ORDER BY depth, d.id
        """,
        {"tenant_id": client.settings.tenant_id, "id": entity_id},
    )


def get_dependents(client: FalkorGraphClient, entity_id: str, max_depth: int = 4):
    depth = _bounded_depth(max_depth)
    return client.read(
        f"""
        MATCH p=(n:Entity {{tenant_id:$tenant_id, id:$id}})<-[:DEPENDS_ON*1..{depth}]-(d:Entity {{tenant_id:$tenant_id}})
        RETURN DISTINCT d, length(p) AS depth
        ORDER BY depth, d.id
        """,
        {"tenant_id": client.settings.tenant_id, "id": entity_id},
    )


def get_owner(client: FalkorGraphClient, entity_id: str, as_of: str | None = None):
    params = {"tenant_id": client.settings.tenant_id, "id": entity_id}
    if as_of:
        params["as_of_us"] = to_epoch_us(as_of)
        time_filter = "AND (r._ts_valid_from_us IS NULL OR r._ts_valid_from_us <= $as_of_us) AND (r._ts_valid_until_us IS NULL OR r._ts_valid_until_us > $as_of_us)"
    else:
        time_filter = "AND r.valid_until IS NULL"
    return client.read(
        f"""
        MATCH (o:Entity {{tenant_id:$tenant_id}})-[r:OWNS]->(e:Entity {{tenant_id:$tenant_id, id:$id}})
        WHERE 1=1 {time_filter}
        RETURN o, r
        ORDER BY r._ts_valid_from_us DESC
        """,
        params,
    )


def get_responsible_people(client: FalkorGraphClient, entity_id: str):
    return client.read(
        """
        MATCH (p:Entity:Person {tenant_id:$tenant_id})-[:RESPONSIBLE_FOR]->(e:Entity {tenant_id:$tenant_id, id:$id})
        RETURN DISTINCT p
        UNION
        MATCH (p:Entity:Person {tenant_id:$tenant_id})-[:MEMBER_OF]->(t:Entity:Team {tenant_id:$tenant_id})-[:OWNS]->
              (e:Entity {tenant_id:$tenant_id, id:$id})
        RETURN DISTINCT p
        """,
        {"tenant_id": client.settings.tenant_id, "id": entity_id},
    )


def get_experts(client: FalkorGraphClient, entity_id: str):
    return client.read(
        """
        MATCH (p:Entity:Person {tenant_id:$tenant_id})-[r:EXPERT_IN]->(e:Entity {tenant_id:$tenant_id, id:$id})
        RETURN p, r.confidence AS confidence
        ORDER BY confidence DESC
        """,
        {"tenant_id": client.settings.tenant_id, "id": entity_id},
    )


def get_claims(client: FalkorGraphClient, subject_id: str):
    return client.read(
        """
        MATCH (c:Entity:Claim {tenant_id:$tenant_id})-[:ABOUT]->(s:Entity {tenant_id:$tenant_id, id:$id})
        OPTIONAL MATCH (c)-[:ASSERTED_BY]->(actor:Entity)
        RETURN c, actor
        ORDER BY c._ts_created_at_us, c.id
        """,
        {"tenant_id": client.settings.tenant_id, "id": subject_id},
    )


def get_evidence(client: FalkorGraphClient, subject_id: str):
    return client.read(
        """
        MATCH (e:Entity:Evidence {tenant_id:$tenant_id})-[:ABOUT]->(s:Entity {tenant_id:$tenant_id, id:$id})
        OPTIONAL MATCH (e)-[:DERIVED_FROM]->(source:Entity)
        RETURN e, source
        ORDER BY e._ts_observed_at_us, e.id
        """,
        {"tenant_id": client.settings.tenant_id, "id": subject_id},
    )


def get_conflicts(client: FalkorGraphClient, subject_id: str):
    return client.read(
        """
        MATCH (a:Entity:Claim {tenant_id:$tenant_id})-[:ABOUT]->(s:Entity {tenant_id:$tenant_id, id:$id})
        MATCH (a)-[r:CONTRADICTS]-(b:Entity:Claim {tenant_id:$tenant_id})
        RETURN DISTINCT a, r, b
        ORDER BY a.id, b.id
        """,
        {"tenant_id": client.settings.tenant_id, "id": subject_id},
    )


def get_policies(client: FalkorGraphClient, subject_id: str):
    return client.read(
        """
        MATCH (p:Entity:Policy {tenant_id:$tenant_id})-[r:GOVERNS]->(s:Entity {tenant_id:$tenant_id, id:$id})
        RETURN p, r
        ORDER BY p._ts_valid_from_us DESC, p.id
        """,
        {"tenant_id": client.settings.tenant_id, "id": subject_id},
    )


def get_history(client: FalkorGraphClient, subject_id: str):
    return client.read(
        """
        MATCH (e:Entity:Event {tenant_id:$tenant_id})-[:ABOUT]->(s:Entity {tenant_id:$tenant_id, id:$id})
        RETURN e
        ORDER BY e._ts_occurred_at_us, e.id
        """,
        {"tenant_id": client.settings.tenant_id, "id": subject_id},
    )
