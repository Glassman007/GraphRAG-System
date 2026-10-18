from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase8_utils import entities_with_label, jaccard_text, jaccard_values, path_text


DEFAULT_WEIGHTS = {
    "goal_overlap": 0.35,
    "system_overlap": 0.20,
    "dataset_overlap": 0.15,
    "stakeholder_overlap": 0.10,
    "requirement_overlap": 0.10,
    "dependency_overlap": 0.10,
}


class InitiativeCollisionService:
    MAX_PROJECTS = 250
    MAX_PAIRS = 2000

    def __init__(self, client: FalkorGraphClient, *, weights: dict[str, float] | None = None):
        self.client = client
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        if abs(sum(self.weights.values()) - 1.0) > 1e-6:
            raise ValueError("collision weights must sum to 1.0")

    @staticmethod
    def _features(snapshot: GraphSnapshot, project_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        project = snapshot.node(project_id) or {}
        systems, datasets, requirements, dependencies, stakeholders, paths = set(), set(), set(), set(), set(), []
        for edge in snapshot.edges_from(project_id, {"DEPENDS_ON", "REQUIRES", "ABOUT", "AFFECTS"}, as_of=as_of):
            target = snapshot.node(edge.target)
            if not target:
                continue
            if has_label(target, "System"):
                systems.add(edge.target)
            if has_label(target, "DataSource"):
                datasets.add(edge.target)
            if edge.type == "REQUIRES":
                requirements.add(edge.target)
            if edge.type == "DEPENDS_ON":
                dependencies.add(edge.target)
            paths.append(path_text(edge))
        for edge in snapshot.edges_to(project_id, {"OWNS", "RESPONSIBLE_FOR", "ABOUT", "MEMBER_OF"}, as_of=as_of):
            source = snapshot.node(edge.source)
            if source and (has_label(source, "Team") or has_label(source, "Person")):
                stakeholders.add(edge.source)
                paths.append(path_text(edge))
        return {
            "project": project,
            "goal": str(project.get("goal") or project.get("objective") or project.get("description") or ""),
            "systems": systems,
            "datasets": datasets,
            "requirements": requirements,
            "dependencies": dependencies,
            "stakeholders": stakeholders,
            "paths": paths,
        }

    @staticmethod
    def _collaboration(snapshot: GraphSnapshot, a: str, b: str, *, as_of: str | None = None) -> list[str]:
        paths = []
        for edge in snapshot.edges_from(a, {"COLLABORATES_WITH"}, as_of=as_of):
            if edge.target == b:
                paths.append(path_text(edge))
        for edge in snapshot.edges_from(b, {"COLLABORATES_WITH"}, as_of=as_of):
            if edge.target == a:
                paths.append(path_text(edge))
        return paths

    def score_pair_from_snapshot(self, snapshot: GraphSnapshot, a: str, b: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        if a == b or not has_label(snapshot.node(a), "Project") or not has_label(snapshot.node(b), "Project"):
            return None
        fa, fb = self._features(snapshot, a, as_of=as_of), self._features(snapshot, b, as_of=as_of)
        dimensions = {
            "goal_overlap": jaccard_text(fa["goal"], fb["goal"]),
            "system_overlap": jaccard_values(fa["systems"], fb["systems"]),
            "dataset_overlap": jaccard_values(fa["datasets"], fb["datasets"]),
            "stakeholder_overlap": jaccard_values(fa["stakeholders"], fb["stakeholders"]),
            "requirement_overlap": jaccard_values(fa["requirements"], fb["requirements"]),
            "dependency_overlap": jaccard_values(fa["dependencies"], fb["dependencies"]),
        }
        score = sum(self.weights[k] * dimensions[k] for k in self.weights)
        collaboration = self._collaboration(snapshot, a, b, as_of=as_of)
        if collaboration:
            classification = "INTENTIONAL_COLLABORATION"
        elif score >= 0.70:
            classification = "HIGH_COLLISION"
        elif score >= 0.40:
            classification = "POSSIBLE_COLLISION"
        else:
            classification = "LOW_OVERLAP"
        shared = {
            "systems": sorted(fa["systems"] & fb["systems"]),
            "datasets": sorted(fa["datasets"] & fb["datasets"]),
            "stakeholders": sorted(fa["stakeholders"] & fb["stakeholders"]),
            "requirements": sorted(fa["requirements"] & fb["requirements"]),
            "dependencies": sorted(fa["dependencies"] & fb["dependencies"]),
        }
        return {
            "project_a": fa["project"],
            "project_b": fb["project"],
            "score": round(score, 4),
            "classification": classification,
            "overlap_dimensions": {k: round(v, 4) for k, v in dimensions.items()},
            "weights": dict(self.weights),
            "shared_graph_entities": shared,
            "explanation_paths": sorted(set(fa["paths"] + fb["paths"] + collaboration)),
            "known_collaboration": collaboration,
            "recommended_review": classification in {"HIGH_COLLISION", "POSSIBLE_COLLISION"},
            "limitations": "goal overlap is lexical metadata; structural graph overlap remains required for candidate generation",
        }

    @staticmethod
    def _candidate_pairs(snapshot: GraphSnapshot, project_ids: list[str], *, as_of: str | None = None, max_pairs: int = 2000) -> list[tuple[str, str]]:
        # Inverted graph-neighborhood index prevents blind O(n^2) comparisons.
        buckets: dict[tuple[str, str], set[str]] = defaultdict(set)
        for pid in project_ids:
            for edge in snapshot.edges_from(pid, {"DEPENDS_ON", "REQUIRES", "ABOUT", "AFFECTS"}, as_of=as_of):
                buckets[(edge.type, edge.target)].add(pid)
            for edge in snapshot.edges_to(pid, {"OWNS", "RESPONSIBLE_FOR"}, as_of=as_of):
                buckets[(edge.type, edge.source)].add(pid)
        pairs = set()
        for values in buckets.values():
            for a, b in combinations(sorted(values), 2):
                pairs.add((a, b))
                if len(pairs) >= max_pairs:
                    return sorted(pairs)
        return sorted(pairs)

    def analyze(self, *, as_of: str | None = None, project_id: str | None = None, min_score: float = 0.0, limit: int = 100) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        projects = entities_with_label(snapshot, "Project", as_of=as_of)[: self.MAX_PROJECTS]
        project_ids = [str(x["id"]) for x in projects]
        if project_id and project_id not in project_ids:
            if not has_label(snapshot.node(project_id), "Project"):
                return {"project_id": project_id, "collisions": [], "error": "PROJECT_NOT_FOUND"}
            project_ids.append(project_id)
        pairs = self._candidate_pairs(snapshot, project_ids, as_of=as_of, max_pairs=self.MAX_PAIRS)
        if project_id:
            pairs = [p for p in pairs if project_id in p]
        results = [self.score_pair_from_snapshot(snapshot, a, b, as_of=as_of) for a, b in pairs]
        results = [x for x in results if x and x["score"] >= min_score]
        results.sort(key=lambda x: (-x["score"], str(x["project_a"].get("id")), str(x["project_b"].get("id"))))
        return {
            "as_of": as_of,
            "candidate_projects": len(project_ids),
            "candidate_pairs_evaluated": len(pairs),
            "collisions": results[:limit],
            "bounds": {"max_projects": self.MAX_PROJECTS, "max_pairs": self.MAX_PAIRS, "limit": limit},
            "graph_required": True,
        }
