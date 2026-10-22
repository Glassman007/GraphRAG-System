"""Deterministic, bounded preview of the current canonical tenant graph.

The preview is a read-only SAMPLE of existing nodes/edges, not a reconstructed
situation or a synthetic answer. The caller must supply a registered graph scope.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from backend.app.api_v1.application import node_visible, sanitize
from backend.app.services.phase4_graph import GraphSnapshot

_PREVIEW_FIELDS = {
    'id', 'name', 'display_name', 'title', 'description', 'status', 'severity',
    '_labels', 'type', 'kind', 'team_type', 'source_ref_id', 'source_record_id',
}


def make_graph_preview(snapshot: GraphSnapshot, *, max_nodes: int = 36,
                       max_edges: int = 80) -> dict[str, Any]:
    if not (1 <= max_nodes <= 100 and 0 <= max_edges <= 250):
        raise ValueError('Preview bounds are outside the supported range')

    visible = {key: node for key, node in snapshot.nodes.items() if node_visible(node, None)}
    edges = [edge for edge in snapshot.edges if edge.source in visible and edge.target in visible
             and GraphSnapshot._edge_active(edge, None)]
    adjacent: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacent[edge.source].add(edge.target)
        adjacent[edge.target].add(edge.source)

    def rank(node_id: str) -> tuple[int, int, str]:
        node = visible[node_id]
        labels = set(node.get('_labels') or [])
        if 'Incident' in labels and str(node.get('status', '')).upper() == 'OPEN':
            priority = 4
        elif 'Incident' in labels:
            priority = 3
        elif labels & {'System', 'Service', 'Project', 'Team'}:
            priority = 2
        else:
            priority = 1
        return (-priority, -len(adjacent[node_id]), node_id)

    ordered = sorted(visible, key=rank)
    selected: set[str] = set()
    # Prefer a well-connected real incident, but ensure a connected preview can be
    # made even for graphs that contain zero Incident nodes (e.g. SQL schemas).
    for seed in ordered:
        if len(selected) >= max_nodes:
            break
        if seed in selected:
            continue
        queue = deque([seed])
        enqueued = {seed}
        while queue and len(selected) < max_nodes:
            node_id = queue.popleft()
            if node_id in selected:
                continue
            selected.add(node_id)
            for neighbor in sorted(adjacent[node_id], key=rank):
                if neighbor not in selected and neighbor not in enqueued:
                    queue.append(neighbor)
                    enqueued.add(neighbor)

    preview_edges = [edge for edge in edges if edge.source in selected and edge.target in selected][:max_edges]
    preview_nodes = [sanitize({key: val for key, val in visible[node_id].items() if key in _PREVIEW_FIELDS})
                     for node_id in ordered if node_id in selected]
    return {
        'nodes': preview_nodes,
        'edges': [{'source': edge.source, 'target': edge.target, 'type': edge.type,
                   'properties': sanitize(edge.properties)} for edge in preview_edges],
        'total_nodes': len(visible),
        'total_edges': len(edges),
        'sampled': len(selected) < len(visible) or len(preview_edges) < len(edges),
    }
