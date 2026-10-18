from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase8_utils import active_edges, node_timestamp_us, node_visible, path_text


PROCESS_LINKS = {
    "ABOUT", "PLAN_HAS_TASK", "HAS_EXECUTION", "HAS_CHECKPOINT", "HAS_BRANCH",
    "PRODUCED", "HANDOFF_FOR", "PROPOSED_ACTION", "HAS_OUTCOME", "BASED_ON",
    "ROOT_CAUSE", "ADDRESSES", "VALIDATED_BY", "APPROVED_BY",
}
DEPENDENCY_LINKS = {"REQUIRES", "BLOCKED_BY", "DEPENDS_ON"}


class OrganizationalProcessReconstructionService:
    MAX_SCOPE_NODES = 500

    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _scope_nodes(snapshot: GraphSnapshot, scope_id: str, *, as_of: str | None, max_depth: int = 4) -> set[str]:
        seen = {scope_id}
        queue = deque([(scope_id, 0)])
        while queue and len(seen) < OrganizationalProcessReconstructionService.MAX_SCOPE_NODES:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue
            for nxt, edge, _ in snapshot.neighbors(current, PROCESS_LINKS, direction="both", as_of=as_of):
                if nxt in seen or not node_visible(snapshot.node(nxt), as_of):
                    continue
                seen.add(nxt)
                queue.append((nxt, depth + 1))
        return seen

    @staticmethod
    def reconstruct_from_snapshot(snapshot: GraphSnapshot, scope_id: str, *, as_of: str | None = None, max_events: int = 250) -> dict[str, Any] | None:
        scope = snapshot.node(scope_id)
        if scope is None or not node_visible(scope, as_of):
            return None
        scope_nodes = OrganizationalProcessReconstructionService._scope_nodes(snapshot, scope_id, as_of=as_of)
        # Any Event that is explicitly linked to a node in the bounded process scope belongs to the process.
        event_ids: set[str] = set()
        for edge in active_edges(snapshot, as_of=as_of, rel_types={"ABOUT"}):
            if edge.target in scope_nodes and has_label(snapshot.node(edge.source), "Event"):
                event_ids.add(edge.source)
            if edge.source in scope_nodes and has_label(snapshot.node(edge.target), "Event"):
                event_ids.add(edge.target)
        if has_label(scope, "Event"):
            event_ids.add(scope_id)
        event_ids = {eid for eid in event_ids if node_visible(snapshot.node(eid), as_of)}
        if len(event_ids) > max_events:
            event_ids = set(sorted(event_ids)[:max_events])

        explicit_before = []
        trigger_edges = []
        for edge in active_edges(snapshot, as_of=as_of, rel_types={"BEFORE", "TRIGGERED"}):
            if edge.source in event_ids and edge.target in event_ids:
                payload = {"source": edge.source, "target": edge.target, "relationship": edge.type, "path": path_text(edge)}
                (explicit_before if edge.type == "BEFORE" else trigger_edges).append(payload)

        dependency_edges = []
        for edge in active_edges(snapshot, as_of=as_of, rel_types=DEPENDENCY_LINKS):
            if edge.source in scope_nodes and edge.target in scope_nodes:
                dependency_edges.append({
                    "source": edge.source,
                    "target": edge.target,
                    "relationship": edge.type,
                    "path": path_text(edge),
                })

        causal_edges = []
        # Explicit validated CAUSE edges are accepted, but chronology is never promoted to causality.
        for edge in active_edges(snapshot, as_of=as_of, rel_types={"CAUSE"}):
            if edge.source in scope_nodes and edge.target in scope_nodes and bool(edge.properties.get("validated", True)):
                causal_edges.append({"source": edge.source, "target": edge.target, "basis": "EXPLICIT_CAUSE", "path": path_text(edge)})
        # A validated ROOT_CAUSE claim is a second supported causal form.
        for edge in active_edges(snapshot, as_of=as_of, rel_types={"ROOT_CAUSE"}):
            if edge.source not in scope_nodes or edge.target not in scope_nodes:
                continue
            source, target = snapshot.node(edge.source) or {}, snapshot.node(edge.target) or {}
            claim_id = edge.target if has_label(target, "Claim") else edge.source if has_label(source, "Claim") else None
            incident_id = edge.source if has_label(source, "Incident") else edge.target if has_label(target, "Incident") else None
            claim = snapshot.node(claim_id) if claim_id else None
            if claim_id and incident_id and str((claim or {}).get("status", "")).upper() in {"VALIDATED", "ACTIVE", "RESOLVED"}:
                support = [e.source for e in snapshot.edges_to(claim_id, {"SUPPORTS"}, as_of=as_of) if has_label(snapshot.node(e.source), "Evidence")]
                if support:
                    causal_edges.append({
                        "source": claim_id,
                        "target": incident_id,
                        "basis": "VALIDATED_ROOT_CAUSE_CLAIM",
                        "supporting_evidence": sorted(support),
                        "path": path_text(edge),
                    })

        before_lookup = {(x["source"], x["target"]) for x in explicit_before}
        steps = []
        timestamps: dict[str, int | None] = {}
        for eid in sorted(event_ids):
            event = snapshot.node(eid) or {}
            ts = node_timestamp_us(event, "occurred_at", "created_at")
            timestamps[eid] = ts
            about = [e.target for e in snapshot.edges_from(eid, {"ABOUT"}, as_of=as_of)]
            actors = [e.target for e in snapshot.edges_from(eid, {"PERFORMED_BY"}, as_of=as_of)]
            triggered_by = [x["source"] for x in trigger_edges if x["target"] == eid]
            dependencies = [x for x in dependency_edges if x["source"] in about or x["target"] in about]
            steps.append({
                "event": event,
                "occurred_at": event.get("occurred_at") or event.get("created_at"),
                "actors": [snapshot.node(a) for a in actors if snapshot.node(a)],
                "about_ids": sorted(set(about)),
                "triggered_by": triggered_by,
                "dependencies": dependencies,
                "provenance_paths": [f"{eid}-[:ABOUT]->{x}" for x in about] + [f"{eid}-[:PERFORMED_BY]->{x}" for x in actors],
            })
        # Sorting is for display only. Equal/incomplete timestamps remain explicitly ambiguous.
        steps.sort(key=lambda s: (timestamps.get(str(s["event"].get("id"))) is None, timestamps.get(str(s["event"].get("id"))) or 0, str(s["event"].get("id"))))

        by_time: dict[int | None, list[str]] = defaultdict(list)
        for eid, ts in timestamps.items():
            by_time[ts].append(eid)
        ambiguous = []
        for ts, ids in by_time.items():
            if ts is None or len(ids) <= 1:
                if ts is None and ids:
                    ambiguous.append({"reason": "MISSING_TIMESTAMP", "event_ids": sorted(ids)})
                continue
            unresolved_pairs = []
            ids = sorted(ids)
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    if (a, b) not in before_lookup and (b, a) not in before_lookup:
                        unresolved_pairs.append([a, b])
            if unresolved_pairs:
                ambiguous.append({"reason": "EQUAL_TIMESTAMP_WITHOUT_ORDER_EDGE", "event_ids": ids, "unresolved_pairs": unresolved_pairs})

        graph_paths = sorted({x["path"] for x in explicit_before + trigger_edges + dependency_edges + causal_edges if x.get("path")})
        return {
            "scope": scope,
            "as_of": as_of,
            "steps": steps,
            "temporal_edges": sorted(explicit_before, key=lambda x: (x["source"], x["target"])),
            "trigger_edges": sorted(trigger_edges, key=lambda x: (x["source"], x["target"])),
            "dependency_edges": sorted(dependency_edges, key=lambda x: (x["source"], x["relationship"], x["target"])),
            "causal_edges": sorted(causal_edges, key=lambda x: (x["source"], x["target"])),
            "ambiguities": ambiguous,
            "graph_paths": graph_paths,
            "semantics": {
                "BEFORE": "temporal ordering only; does not imply causation",
                "TRIGGERED": "explicit workflow initiation",
                "DEPENDENCY": "REQUIRES/BLOCKED_BY/DEPENDS_ON prerequisite semantics",
                "CAUSE": "returned only from explicit/validated causal graph evidence",
            },
            "graph_required": True,
        }

    def reconstruct(self, scope_id: str, *, as_of: str | None = None, max_events: int = 250) -> dict[str, Any] | None:
        return self.reconstruct_from_snapshot(GraphSnapshot.load(self.client), scope_id, as_of=as_of, max_events=max_events)
