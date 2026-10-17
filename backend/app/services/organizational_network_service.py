from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase8_utils import active_edges, node_visible, path_text


class OrganizationalNetworkAnalysisService:
    MAX_NODES = 300
    MAX_EDGES = 1500

    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _add_edge(adj: dict[str, set[str]], evidence: dict[tuple[str, str], list[str]], a: str, b: str, reason: str) -> None:
        if a == b:
            return
        adj[a].add(b); adj[b].add(a)
        key = tuple(sorted((a, b)))
        evidence[key].append(reason)

    @staticmethod
    def projection_from_snapshot(snapshot: GraphSnapshot, projection: str, *, as_of: str | None = None, max_nodes: int = 300, max_edges: int = 1500) -> dict[str, Any]:
        adj: dict[str, set[str]] = defaultdict(set)
        evidence: dict[tuple[str, str], list[str]] = defaultdict(list)
        node_ids: set[str] = set()
        projection = projection.lower()

        if projection == "system_dependency":
            for edge in active_edges(snapshot, as_of=as_of, rel_types={"DEPENDS_ON"}):
                a, b = snapshot.node(edge.source), snapshot.node(edge.target)
                if a and b and has_label(a, "System") and has_label(b, "System"):
                    node_ids.update([edge.source, edge.target]); OrganizationalNetworkAnalysisService._add_edge(adj, evidence, edge.source, edge.target, path_text(edge))

        elif projection == "ownership":
            for edge in active_edges(snapshot, as_of=as_of, rel_types={"OWNS", "RESPONSIBLE_FOR", "EXPERT_IN"}):
                a, b = snapshot.node(edge.source), snapshot.node(edge.target)
                if a and b and (has_label(a, "Person") or has_label(a, "Team") or has_label(a, "Agent")) and (has_label(b, "System") or has_label(b, "Project")):
                    node_ids.update([edge.source, edge.target]); OrganizationalNetworkAnalysisService._add_edge(adj, evidence, edge.source, edge.target, path_text(edge))

        elif projection == "approval":
            for edge in active_edges(snapshot, as_of=as_of, rel_types={"APPROVED_BY"}):
                actor = snapshot.node(edge.target); object_node = snapshot.node(edge.source)
                if actor and object_node and (has_label(actor, "Person") or has_label(actor, "Team") or has_label(actor, "Agent")):
                    node_ids.update([edge.source, edge.target]); OrganizationalNetworkAnalysisService._add_edge(adj, evidence, edge.source, edge.target, path_text(edge))

        elif projection == "collaboration":
            actors = {nid for nid, n in snapshot.nodes.items() if (has_label(n, "Person") or has_label(n, "Team")) and node_visible(n, as_of)}
            # Direct membership is a real organizational connection.
            for edge in active_edges(snapshot, as_of=as_of, rel_types={"MEMBER_OF", "COLLABORATES_WITH"}):
                if edge.source in actors and edge.target in actors:
                    node_ids.update([edge.source, edge.target]); OrganizationalNetworkAnalysisService._add_edge(adj, evidence, edge.source, edge.target, path_text(edge))
            # Shared project participation creates an explainable projected collaboration edge.
            participation: dict[str, list[tuple[str, str]]] = defaultdict(list)
            for edge in active_edges(snapshot, as_of=as_of, rel_types={"OWNS", "RESPONSIBLE_FOR", "DEPENDS_ON", "ABOUT"}):
                source, target = snapshot.node(edge.source), snapshot.node(edge.target)
                if edge.source in actors and target and has_label(target, "Project"):
                    participation[edge.target].append((edge.source, path_text(edge)))
                elif edge.target in actors and source and has_label(source, "Project"):
                    participation[edge.source].append((edge.target, path_text(edge)))
            for project_id, values in participation.items():
                values = sorted(values)
                for i, (a, pa) in enumerate(values):
                    for b, pb in values[i + 1:]:
                        node_ids.update([a, b]); OrganizationalNetworkAnalysisService._add_edge(adj, evidence, a, b, f"{pa} ; {pb} (shared project {project_id})")
        else:
            raise ValueError("projection must be one of: collaboration, system_dependency, ownership, approval")

        node_ids = set(sorted(node_ids)[:max_nodes])
        filtered_adj: dict[str, set[str]] = {n: {x for x in adj.get(n, set()) if x in node_ids} for n in node_ids}
        edges = []
        for a in sorted(node_ids):
            for b in sorted(filtered_adj[a]):
                if a < b:
                    edges.append((a, b))
                    if len(edges) >= max_edges:
                        break
            if len(edges) >= max_edges:
                break
        allowed = set(edges)
        filtered_adj = {n: set() for n in node_ids}
        for a, b in edges:
            filtered_adj[a].add(b); filtered_adj[b].add(a)
        return {
            "projection": projection,
            "nodes": {nid: snapshot.node(nid) for nid in sorted(node_ids)},
            "adjacency": filtered_adj,
            "edges": edges,
            "evidence": {f"{a}|{b}": sorted(set(evidence.get((a, b), evidence.get((b, a), [])))) for a, b in edges},
            "bounds": {"max_nodes": max_nodes, "max_edges": max_edges},
        }

    @staticmethod
    def _components(adj: dict[str, set[str]]) -> list[list[str]]:
        seen, comps = set(), []
        for start in sorted(adj):
            if start in seen:
                continue
            stack, comp = [start], []
            seen.add(start)
            while stack:
                node = stack.pop(); comp.append(node)
                for nxt in sorted(adj.get(node, set()), reverse=True):
                    if nxt not in seen:
                        seen.add(nxt); stack.append(nxt)
            comps.append(sorted(comp))
        return comps

    @staticmethod
    def _articulation_and_bridges(adj: dict[str, set[str]]) -> tuple[list[str], list[tuple[str, str]]]:
        disc, low, parent = {}, {}, {}
        time = 0
        arts: set[str] = set(); bridges: set[tuple[str, str]] = set()

        def dfs(u: str):
            nonlocal time
            time += 1; disc[u] = low[u] = time
            children = 0
            for v in sorted(adj.get(u, set())):
                if v not in disc:
                    parent[v] = u; children += 1; dfs(v); low[u] = min(low[u], low[v])
                    if u not in parent and children > 1:
                        arts.add(u)
                    if u in parent and low[v] >= disc[u]:
                        arts.add(u)
                    if low[v] > disc[u]:
                        bridges.add(tuple(sorted((u, v))))
                elif parent.get(u) != v:
                    low[u] = min(low[u], disc[v])
        for node in sorted(adj):
            if node not in disc:
                dfs(node)
        return sorted(arts), sorted(bridges)

    @staticmethod
    def _betweenness(adj: dict[str, set[str]]) -> dict[str, float]:
        nodes = sorted(adj); cb = {v: 0.0 for v in nodes}
        for s in nodes:
            stack = []; pred = {w: [] for w in nodes}; sigma = dict.fromkeys(nodes, 0.0); sigma[s] = 1.0
            dist = dict.fromkeys(nodes, -1); dist[s] = 0
            q = deque([s])
            while q:
                v = q.popleft(); stack.append(v)
                for w in sorted(adj.get(v, set())):
                    if dist[w] < 0:
                        q.append(w); dist[w] = dist[v] + 1
                    if dist[w] == dist[v] + 1:
                        sigma[w] += sigma[v]; pred[w].append(v)
            delta = dict.fromkeys(nodes, 0.0)
            while stack:
                w = stack.pop()
                if sigma[w]:
                    for v in pred[w]:
                        delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
                if w != s:
                    cb[w] += delta[w]
        # undirected graph counted twice
        for v in cb:
            cb[v] /= 2.0
        n = len(nodes)
        if n > 2:
            scale = 2.0 / ((n - 1) * (n - 2))
            cb = {v: cb[v] * scale for v in nodes}
        else:
            cb = {v: 0.0 for v in nodes}
        return cb

    @staticmethod
    def analyze_projection(snapshot: GraphSnapshot, projection: str, *, as_of: str | None = None, max_nodes: int = 300, max_edges: int = 1500) -> dict[str, Any]:
        proj = OrganizationalNetworkAnalysisService.projection_from_snapshot(snapshot, projection, as_of=as_of, max_nodes=max_nodes, max_edges=max_edges)
        adj = proj["adjacency"]; n = len(adj)
        degree = {node: (len(neigh) / (n - 1) if n > 1 else 0.0) for node, neigh in adj.items()}
        betweenness = OrganizationalNetworkAnalysisService._betweenness(adj)
        arts, bridges = OrganizationalNetworkAnalysisService._articulation_and_bridges(adj)
        components_before = OrganizationalNetworkAnalysisService._components(adj)
        articulation_details = []
        for node in arts:
            reduced = {k: {x for x in v if x != node} for k, v in adj.items() if k != node}
            comps_after = OrganizationalNetworkAnalysisService._components(reduced)
            articulation_details.append({
                "node": proj["nodes"][node],
                "components_before": len(components_before),
                "components_after": len(comps_after),
                "affected_components": comps_after,
                "explanation": f"removing {node} increases connected components from {len(components_before)} to {len(comps_after)}",
            })
        bridge_details = []
        for a, b in bridges:
            bridge_details.append({
                "source": proj["nodes"][a], "target": proj["nodes"][b],
                "evidence_paths": proj["evidence"].get(f"{a}|{b}", []),
                "explanation": "removing this projected edge disconnects its connected component",
            })
        # Deterministic bridge-separated communities. This is not labeled as a social silo detector.
        bridge_set = set(bridges)
        no_bridge_adj = {n: {x for x in neigh if tuple(sorted((n, x))) not in bridge_set} for n, neigh in adj.items()}
        communities = OrganizationalNetworkAnalysisService._components(no_bridge_adj)
        community_index = {node: idx for idx, comp in enumerate(communities) for node in comp}
        boundaries = [
            {"source": a, "target": b, "community_a": community_index.get(a), "community_b": community_index.get(b)}
            for a, b in bridges if community_index.get(a) != community_index.get(b)
        ]

        overloaded = []
        for node_id in sorted(adj):
            node = proj["nodes"][node_id] or {}
            active_tasks = 0; approvals = 0; critical_owned = 0; commitments = 0
            for edge in snapshot.edges_from(node_id, {"CANDIDATE_FOR"}, as_of=as_of):
                task = snapshot.node(edge.target) or {}
                if has_label(task, "Task") and str(task.get("status") or "").upper() in {"OPEN", "READY", "CLAIMED", "IN_PROGRESS", "BLOCKED", "PENDING"}:
                    active_tasks += 1
            for edge in snapshot.edges_to(node_id, {"CLAIMED_BY", "ASSIGNED_TO"}, as_of=as_of):
                task = snapshot.node(edge.source) or {}
                if has_label(task, "Task") and str(task.get("status") or "").upper() in {"OPEN", "READY", "CLAIMED", "IN_PROGRESS", "BLOCKED", "PENDING"}:
                    active_tasks += 1
            approvals = len(snapshot.edges_to(node_id, {"APPROVED_BY"}, as_of=as_of))
            for edge in snapshot.edges_from(node_id, {"OWNS"}, as_of=as_of):
                target = snapshot.node(edge.target) or {}
                if str(target.get("criticality") or "").upper() in {"HIGH", "CRITICAL"}:
                    critical_owned += 1
            commitments = len(snapshot.edges_to(node_id, {"PROMISED_BY", "OWED_TO"}, as_of=as_of))
            load_score = active_tasks + approvals + critical_owned + commitments
            if betweenness.get(node_id, 0.0) >= 0.25 and load_score >= 3:
                overloaded.append({
                    "node": node,
                    "betweenness": round(betweenness[node_id], 6),
                    "load_score": load_score,
                    "signals": {"active_tasks": active_tasks, "approval_obligations": approvals, "critical_owned_systems": critical_owned, "active_commitments": commitments},
                    "explanation": "high structural brokerage combined with multiple operational load signals",
                })

        centrality = [
            {"node": proj["nodes"][nid], "degree_centrality": round(degree[nid], 6), "betweenness_centrality": round(betweenness[nid], 6)}
            for nid in sorted(adj)
        ]
        centrality.sort(key=lambda x: (-x["betweenness_centrality"], -x["degree_centrality"], str(x["node"].get("id"))))
        return {
            "projection": projection,
            "as_of": as_of,
            "node_count": len(proj["nodes"]),
            "edge_count": len(proj["edges"]),
            "centrality": centrality,
            "articulation_points": articulation_details,
            "bridges": bridge_details,
            "communities": communities,
            "community_boundaries": boundaries,
            "overloaded_nodes": overloaded,
            "single_path_risks": bridge_details,
            "projection_edges": [{"source": a, "target": b, "evidence_paths": proj["evidence"].get(f"{a}|{b}", [])} for a, b in proj["edges"]],
            "algorithms": {
                "degree": "normalized undirected degree within the named projection",
                "betweenness": "Brandes unweighted betweenness, normalized for undirected graph",
                "articulation_points": "Tarjan DFS low-link",
                "bridges": "Tarjan DFS low-link",
                "communities": "connected components after removing bridge edges; evidence for review, not proof of silos",
            },
            "bounds": proj["bounds"],
            "graph_required": True,
        }

    def analyze(self, projection: str = "collaboration", *, as_of: str | None = None, max_nodes: int = 300, max_edges: int = 1500) -> dict[str, Any]:
        max_nodes = min(max(1, max_nodes), self.MAX_NODES)
        max_edges = min(max(1, max_edges), self.MAX_EDGES)
        return self.analyze_projection(GraphSnapshot.load(self.client), projection, as_of=as_of, max_nodes=max_nodes, max_edges=max_edges)
