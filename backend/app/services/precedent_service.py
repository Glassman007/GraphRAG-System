from __future__ import annotations

from collections import Counter
import re

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot, has_label


def _counter_jaccard(a: Counter, b: Counter) -> float:
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    inter = sum(min(a[k], b[k]) for k in keys)
    union = sum(max(a[k], b[k]) for k in keys)
    return inter / union if union else 0.0


def _token_jaccard(a: str, b: str) -> float:
    ta = set(re.findall(r"[a-z0-9]+", (a or "").lower()))
    tb = set(re.findall(r"[a-z0-9]+", (b or "").lower()))
    return len(ta & tb) / len(ta | tb) if ta | tb else 0.0


class StructuralPrecedentService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    @staticmethod
    def _motif(snapshot: GraphSnapshot, incident_id: str) -> dict:
        evidence_ids = {e.source for e in snapshot.edges_to(incident_id, {"ABOUT"}) if has_label(snapshot.node(e.source), "Evidence")}
        change_ids = set()
        for eid in evidence_ids:
            for edge in snapshot.edges_from(eid, {"ABOUT"}):
                if has_label(snapshot.node(edge.target), "Change"):
                    change_ids.add(edge.target)
        features: Counter = Counter()
        generic_features: Counter = Counter()
        evidence_types = Counter()
        system_ids: set[str] = set()
        explanation = []
        for eid in evidence_ids:
            ev = snapshot.node(eid) or {}
            evidence_types[str(ev.get("evidence_type") or "unknown")] += 1
        for cid in change_ids:
            change = snapshot.node(cid) or {}
            features[f"change_type:{change.get('change_type','unknown')}"] += 1
            for edge in snapshot.edges_from(cid, {"CHANGED", "AFFECTS"}):
                target = snapshot.node(edge.target) or {}
                st = target.get("system_type", "unknown")
                generic_features[f"motif:change-{edge.type.lower()}-system"] = 1
                features[f"motif:change-{edge.type.lower()}-system"] += 1
                features[f"{edge.type}->system:{st}"] += 1
                system_ids.add(edge.target)
                explanation.append(f"{cid}-[:{edge.type}]->{edge.target}")
                # Include dependency motif around the affected system, not names.
                for dep in snapshot.edges_to(edge.target, {"DEPENDS_ON"}):
                    source = snapshot.node(dep.source) or {}
                    generic_features["motif:dependent-to-changed-target"] = 1
                    features["motif:dependent-to-changed-target"] += 1
                    features[f"dependent:{source.get('system_type','unknown')}->target:{st}"] += 1
                    system_ids.add(dep.source)
                    explanation.append(f"{dep.source}-[:DEPENDS_ON]->{edge.target}")
                for dep in snapshot.edges_from(edge.target, {"DEPENDS_ON"}):
                    target2 = snapshot.node(dep.target) or {}
                    features[f"source:{st}->dependency:{target2.get('system_type','unknown')}"] += 1
                    system_ids.add(dep.target)
                    explanation.append(f"{edge.target}-[:DEPENDS_ON]->{dep.target}")
        if evidence_ids and change_ids:
            generic_features["motif:evidence-bridges-incident-change"] = 1
            features["motif:evidence-bridges-incident-change"] += 1
        return {
            "features": features,
            "generic_features": generic_features,
            "evidence_types": evidence_types,
            "evidence_ids": sorted(evidence_ids),
            "change_ids": sorted(change_ids),
            "system_ids": sorted(system_ids),
            "explanation_paths": sorted(set(explanation)),
        }

    def find_precedents(self, incident_id: str, *, limit: int = 10) -> dict | None:
        snapshot = GraphSnapshot.load(self.client)
        incident = snapshot.node(incident_id)
        if incident is None or not has_label(incident, "Incident"):
            return None
        base = self._motif(snapshot, incident_id)
        results = []
        for candidate_id, candidate in snapshot.nodes.items():
            if candidate_id == incident_id or not has_label(candidate, "Incident"):
                continue
            motif = self._motif(snapshot, candidate_id)
            structural = _counter_jaccard(base["generic_features"], motif["generic_features"])
            evidence_similarity = _counter_jaccard(base["evidence_types"], motif["evidence_types"])
            severity = 1.0 if incident.get("severity") == candidate.get("severity") else 0.0
            keyword = _token_jaccard(str(incident.get("title", "")), str(candidate.get("title", "")))
            # Semantic metadata is secondary. Keyword overlap alone cannot exceed 5% of final score.
            semantic = 0.60 * evidence_similarity + 0.25 * severity + 0.15 * keyword
            final = 0.75 * structural + 0.25 * semantic
            if structural <= 0:
                continue
            results.append({
                "incident": candidate,
                "score": round(final, 4),
                "structural_similarity": round(structural, 4),
                "semantic_similarity": round(semantic, 4),
                "keyword_component": round(keyword, 4),
                "matching_evidence": [snapshot.node(eid) for eid in motif["evidence_ids"]],
                "explanation_paths": motif["explanation_paths"],
                "structural_signature": dict(motif["features"]),
            })
        results.sort(key=lambda x: (-x["score"], str(x["incident"].get("id"))))
        return {"incident": incident, "precedents": results[:limit], "graph_required": True}
