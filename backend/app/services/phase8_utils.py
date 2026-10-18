from __future__ import annotations

import re
from collections import deque
from typing import Any, Iterable

from backend.app.graph.temporal import to_epoch_us
from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot, has_label


def tokens(value: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (value or "").lower()))


def jaccard_values(a: Iterable[str], b: Iterable[str]) -> float:
    left, right = set(a), set(b)
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def jaccard_text(a: str | None, b: str | None) -> float:
    return jaccard_values(tokens(a), tokens(b))


def node_timestamp_us(node: dict[str, Any], *fields: str) -> int | None:
    for field in fields:
        value = node.get(field)
        if value:
            return to_epoch_us(str(value))
    return None


def node_visible(node: dict[str, Any] | None, as_of: str | None) -> bool:
    if not node:
        return False
    if as_of is None:
        return str(node.get("status") or "").upper() not in {"DELETED"}
    point = to_epoch_us(as_of)
    created = node.get("created_at") or node.get("observed_at") or node.get("occurred_at")
    if created and to_epoch_us(str(created)) > point:
        return False
    valid_from = node.get("valid_from")
    valid_until = node.get("valid_until")
    if valid_from and to_epoch_us(str(valid_from)) > point:
        return False
    if valid_until and to_epoch_us(str(valid_until)) <= point:
        return False
    return True


def active_edges(snapshot: GraphSnapshot, *, as_of: str | None = None, rel_types: set[str] | None = None) -> list[GraphEdge]:
    return [
        edge for edge in snapshot.edges
        if (rel_types is None or edge.type in rel_types) and snapshot._edge_active(edge, as_of)
    ]


def path_text(edge: GraphEdge) -> str:
    return f"{edge.source}-[:{edge.type}]->{edge.target}"


def shortest_path(
    snapshot: GraphSnapshot,
    start: str,
    target: str,
    *,
    rel_types: set[str] | None = None,
    max_depth: int = 6,
    as_of: str | None = None,
    direction: str = "both",
) -> dict[str, Any] | None:
    if start == target:
        return {"node_ids": [start], "edges": []}
    queue = deque([(start, [start], [])])
    while queue:
        current, nodes, edges = queue.popleft()
        if len(edges) >= max_depth:
            continue
        for nxt, edge, _ in snapshot.neighbors(current, rel_types, direction=direction, as_of=as_of):
            if nxt in nodes:
                continue
            n_nodes, n_edges = nodes + [nxt], edges + [edge]
            if nxt == target:
                return {"node_ids": n_nodes, "edges": [e.as_dict() for e in n_edges]}
            queue.append((nxt, n_nodes, n_edges))
    return None


def entities_with_label(snapshot: GraphSnapshot, label: str, *, as_of: str | None = None) -> list[dict[str, Any]]:
    return sorted(
        [n for n in snapshot.nodes.values() if has_label(n, label) and node_visible(n, as_of)],
        key=lambda n: str(n.get("id")),
    )
