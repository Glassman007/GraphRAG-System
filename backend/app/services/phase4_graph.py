from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Iterable

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.temporal import public_properties, to_epoch_us
from backend.app.services.phase3_utils import node_dict


def relationship_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return public_properties(value)
    if hasattr(value, "properties"):
        return public_properties(value.properties)
    return {}


@dataclass(frozen=True)
class GraphEdge:
    source: str
    type: str
    target: str
    properties: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "type": self.type, "target": self.target, "properties": dict(self.properties)}


class GraphSnapshot:
    """Tenant graph read from FalkorDB. Algorithms may derive results in memory, but truth comes from graph reads."""

    def __init__(self, nodes: dict[str, dict[str, Any]], edges: list[GraphEdge]):
        self.nodes = nodes
        self.edges = edges
        self.outgoing: dict[str, list[GraphEdge]] = defaultdict(list)
        self.incoming: dict[str, list[GraphEdge]] = defaultdict(list)
        for edge in edges:
            self.outgoing[edge.source].append(edge)
            self.incoming[edge.target].append(edge)

    @classmethod
    def load(cls, client: FalkorGraphClient) -> "GraphSnapshot":
        node_result = client.read(
            "MATCH (n:Entity {tenant_id:$tenant_id}) RETURN n ORDER BY n.id",
            {"tenant_id": client.settings.tenant_id},
        )
        nodes: dict[str, dict[str, Any]] = {}
        for row in node_result.result_set:
            item = node_dict(row[0]) or {}
            if item.get("id"):
                nodes[str(item["id"])] = item

        edge_result = client.read(
            """
            MATCH (a:Entity {tenant_id:$tenant_id})-[r]->(b:Entity {tenant_id:$tenant_id})
            RETURN a.id, type(r), r, b.id
            ORDER BY a.id, type(r), b.id
            """,
            {"tenant_id": client.settings.tenant_id},
        )
        edges = [
            GraphEdge(str(row[0]), str(row[1]), str(row[3]), relationship_dict(row[2]))
            for row in edge_result.result_set
        ]
        return cls(nodes, edges)

    def node(self, entity_id: str) -> dict[str, Any] | None:
        return self.nodes.get(entity_id)

    @staticmethod
    def _edge_active(edge: GraphEdge, as_of: str | None) -> bool:
        if as_of is None:
            return edge.properties.get("valid_until") is None
        point = to_epoch_us(as_of)
        vf = edge.properties.get("valid_from")
        vu = edge.properties.get("valid_until")
        if vf is not None and to_epoch_us(vf) > point:
            return False
        if vu is not None and to_epoch_us(vu) <= point:
            return False
        return True

    def edges_from(self, entity_id: str, rel_types: set[str] | None = None, *, as_of: str | None = None) -> list[GraphEdge]:
        values = self.outgoing.get(entity_id, [])
        return [e for e in values if (rel_types is None or e.type in rel_types) and self._edge_active(e, as_of)]

    def edges_to(self, entity_id: str, rel_types: set[str] | None = None, *, as_of: str | None = None) -> list[GraphEdge]:
        values = self.incoming.get(entity_id, [])
        return [e for e in values if (rel_types is None or e.type in rel_types) and self._edge_active(e, as_of)]

    def neighbors(
        self,
        entity_id: str,
        rel_types: set[str] | None = None,
        *,
        direction: str = "both",
        as_of: str | None = None,
    ) -> list[tuple[str, GraphEdge, str]]:
        out: list[tuple[str, GraphEdge, str]] = []
        if direction in {"out", "both"}:
            out.extend((e.target, e, "out") for e in self.edges_from(entity_id, rel_types, as_of=as_of))
        if direction in {"in", "both"}:
            out.extend((e.source, e, "in") for e in self.edges_to(entity_id, rel_types, as_of=as_of))
        return out

    def bounded_paths(
        self,
        start_id: str,
        *,
        targets: set[str] | None = None,
        rel_types: set[str] | None = None,
        max_depth: int = 6,
        direction: str = "both",
        max_paths: int = 100,
        as_of: str | None = None,
    ) -> list[dict[str, Any]]:
        if max_depth < 1 or max_depth > 8:
            raise ValueError("max_depth must be between 1 and 8")
        if start_id not in self.nodes:
            return []
        results: list[dict[str, Any]] = []
        queue = deque([(start_id, [start_id], [])])
        while queue and len(results) < max_paths:
            current, node_path, edge_path = queue.popleft()
            if current != start_id and (targets is None or current in targets):
                results.append({"node_ids": list(node_path), "edges": [e.as_dict() for e in edge_path]})
                if targets is not None and current in targets:
                    continue
            if len(edge_path) >= max_depth:
                continue
            for nxt, edge, _ in self.neighbors(current, rel_types, direction=direction, as_of=as_of):
                if nxt in node_path:
                    continue
                queue.append((nxt, node_path + [nxt], edge_path + [edge]))
        return results

    def dependency_reachability(self, root_id: str, *, reverse: bool, max_depth: int = 6, as_of: str | None = None) -> list[dict[str, Any]]:
        if max_depth < 1 or max_depth > 8:
            raise ValueError("max_depth must be between 1 and 8")
        direction = "in" if reverse else "out"
        queue = deque([(root_id, [root_id], [])])
        best: dict[str, dict[str, Any]] = {}
        while queue:
            current, nodes, edges = queue.popleft()
            if len(edges) >= max_depth:
                continue
            for nxt, edge, _ in self.neighbors(current, {"DEPENDS_ON"}, direction=direction, as_of=as_of):
                if nxt in nodes:
                    continue
                candidate = {"entity_id": nxt, "depth": len(edges) + 1, "node_ids": nodes + [nxt], "edges": [e.as_dict() for e in edges + [edge]]}
                prior = best.get(nxt)
                if prior is None or candidate["depth"] < prior["depth"]:
                    best[nxt] = candidate
                    queue.append((nxt, nodes + [nxt], edges + [edge]))
        return sorted(best.values(), key=lambda x: (x["depth"], x["entity_id"]))

    def clone(self) -> "GraphSnapshot":
        return GraphSnapshot(
            {key: dict(value) for key, value in self.nodes.items()},
            [GraphEdge(e.source, e.type, e.target, dict(e.properties)) for e in self.edges],
        )

    def remove_edges(self, predicate) -> int:
        before = len(self.edges)
        self.edges = [e for e in self.edges if not predicate(e)]
        self._reindex()
        return before - len(self.edges)

    def add_edge(self, source: str, rel_type: str, target: str, properties: dict[str, Any] | None = None) -> None:
        self.edges.append(GraphEdge(source, rel_type, target, dict(properties or {})))
        self._reindex()

    def _reindex(self) -> None:
        self.outgoing = defaultdict(list)
        self.incoming = defaultdict(list)
        for edge in self.edges:
            self.outgoing[edge.source].append(edge)
            self.incoming[edge.target].append(edge)


def labels_of(node: dict[str, Any] | None) -> set[str]:
    if not node:
        return set()
    return set(node.get("_labels") or [])


def has_label(node: dict[str, Any] | None, label: str) -> bool:
    return label in labels_of(node)


def edge_path_text(snapshot: GraphSnapshot, path: dict[str, Any]) -> str:
    node_ids = path.get("node_ids", [])
    edges = path.get("edges", [])
    if not node_ids:
        return ""
    parts = [node_ids[0]]
    for idx, edge in enumerate(edges):
        source, target, rel = edge["source"], edge["target"], edge["type"]
        current = node_ids[idx]
        nxt = node_ids[idx + 1]
        if source == current and target == nxt:
            parts.append(f"-[:{rel}]-> {nxt}")
        else:
            parts.append(f"<-[:{rel}]- {nxt}")
    return " ".join(parts)
