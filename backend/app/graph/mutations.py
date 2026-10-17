from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.schema import validate_label, validate_relationship
from backend.app.graph.temporal import with_temporal_epochs


def _edge_id(source_id: str, rel_type: str, target_id: str, props: dict[str, Any]) -> str:
    valid_from = props.get("valid_from", "")
    return str(props.get("edge_id") or f"{source_id}|{rel_type}|{target_id}|{valid_from}")


def upsert_node(client: FalkorGraphClient, label: str, node_id: str, properties: dict[str, Any]) -> Any:
    label = validate_label(label)
    props = with_temporal_epochs(properties)
    props["id"] = node_id
    props.setdefault("tenant_id", client.settings.tenant_id)
    cypher = f"""
    MERGE (n:Entity:{label} {{tenant_id: $tenant_id, id: $id}})
    SET n += $props
    RETURN n
    """
    result = client.query(cypher, {"tenant_id": props["tenant_id"], "id": node_id, "props": props})
    return result.result_set[0][0] if result.result_set else None


def upsert_relationship(
    client: FalkorGraphClient,
    source_id: str,
    rel_type: str,
    target_id: str,
    properties: dict[str, Any] | None = None,
) -> Any:
    rel_type = validate_relationship(rel_type)
    props = with_temporal_epochs(properties or {})
    props.setdefault("edge_id", _edge_id(source_id, rel_type, target_id, props))
    cypher = f"""
    MATCH (a:Entity {{tenant_id: $tenant_id, id: $source_id}})
    MATCH (b:Entity {{tenant_id: $tenant_id, id: $target_id}})
    MERGE (a)-[r:{rel_type} {{edge_id: $edge_id}}]->(b)
    SET r += $props
    RETURN r
    """
    result = client.query(
        cypher,
        {
            "tenant_id": client.settings.tenant_id,
            "source_id": source_id,
            "target_id": target_id,
            "edge_id": props["edge_id"],
            "props": props,
        },
    )
    return result.result_set[0][0] if result.result_set else None


def delete_relationship(client: FalkorGraphClient, source_id: str, rel_type: str, target_id: str) -> int:
    rel_type = validate_relationship(rel_type)
    cypher = f"""
    MATCH (a:Entity {{tenant_id: $tenant_id, id: $source_id}})-[r:{rel_type}]->
          (b:Entity {{tenant_id: $tenant_id, id: $target_id}})
    DELETE r
    """
    result = client.query(cypher, {
        "tenant_id": client.settings.tenant_id,
        "source_id": source_id,
        "target_id": target_id,
    })
    return int(result.relationships_deleted)
