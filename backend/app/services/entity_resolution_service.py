from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_relationship
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase3_utils import now_iso


def _tokens(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def _name_score(source: dict[str, Any], candidate: dict[str, Any]) -> float:
    s = (source.get("name") or "").strip().lower()
    c = (candidate.get("name") or "").strip().lower()
    if not s or not c:
        return 0.0
    if s == c:
        return 1.0
    aliases = {str(x).lower() for x in candidate.get("aliases", [])} if isinstance(candidate.get("aliases"), list) else set()
    if s in aliases:
        return 1.0
    st, ct = _tokens(s), _tokens(c)
    if len(st) == 2 and len(ct) == 2 and st[1] == ct[1] and st[0][:1] == ct[0][:1]:
        return 0.84
    return SequenceMatcher(a=s, b=c).ratio()


def _email_score(source: dict[str, Any], candidate: dict[str, Any]) -> float:
    source_email = str(source.get("email") or "").strip().lower()
    candidate_email = str(candidate.get("email") or "").strip().lower()
    return 1.0 if source_email and candidate_email and source_email == candidate_email else 0.0


def _alias_score(source: dict[str, Any], candidate: dict[str, Any]) -> float:
    aliases = set()
    for value in (source.get("username"), source.get("source_entity_id")):
        if value:
            aliases.add(str(value).strip().lower())
    candidate_aliases = candidate.get("aliases") if isinstance(candidate.get("aliases"), list) else []
    for value in (candidate.get("username"), candidate.get("source_entity_id"), *candidate_aliases):
        if value and str(value).strip().lower() in aliases:
            return 1.0
    return 0.0


def _context_score(source: dict[str, Any], candidate_id: str, snapshot: GraphSnapshot) -> tuple[float, list[str]]:
    expected_team = source.get("team_id")
    expected_systems = set(source.get("system_ids") or []) if isinstance(source.get("system_ids"), list) else set()
    matched: list[str] = []
    checks = 0
    hits = 0
    if expected_team:
        checks += 1
        if any(e.target == expected_team for e in snapshot.edges_from(candidate_id, {"MEMBER_OF"})):
            hits += 1
            matched.append(f"{candidate_id}-[:MEMBER_OF]->{expected_team}")
    for system_id in expected_systems:
        checks += 1
        if any(e.target == system_id for e in snapshot.edges_from(candidate_id, {"RESPONSIBLE_FOR", "EXPERT_IN"})):
            hits += 1
            matched.append(f"{candidate_id}-[:RESPONSIBLE_FOR|EXPERT_IN]->{system_id}")
    return (hits / checks if checks else 0.0), matched


class EntityResolutionService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def resolve_source_record(self, source_record_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        source = snapshot.node(source_record_id)
        if source is None or not has_label(source, "SourceRecord"):
            return None

        accepted_edges = snapshot.edges_from(source_record_id, {"REPRESENTS"})
        if accepted_edges:
            edge = sorted(accepted_edges, key=lambda e: float(e.properties.get("confidence") or 0), reverse=True)[0]
            return {
                "source_record": source,
                "status": "CONFIRMED",
                "canonical_entity": snapshot.node(edge.target),
                "confidence": float(edge.properties.get("confidence") or 1.0),
                "candidates": [],
                "explanation": [f"{source_record_id}-[:REPRESENTS]->{edge.target}"],
            }

        explicit = {e.target: e for e in snapshot.edges_from(source_record_id, {"CANDIDATE_MATCH"})}
        candidate_label = str(source.get("candidate_label") or source.get("entity_type") or "Person")
        candidate_nodes = [n for n in snapshot.nodes.values() if has_label(n, candidate_label) and n.get("id") != source_record_id]
        scored: list[dict[str, Any]] = []
        for candidate in candidate_nodes:
            cid = str(candidate["id"])
            name = _name_score(source, candidate)
            email = _email_score(source, candidate)
            alias = _alias_score(source, candidate)
            context, context_paths = _context_score(source, cid, snapshot)
            explicit_edge = explicit.get(cid)
            explicit_conf = float(explicit_edge.properties.get("confidence") or 0.0) if explicit_edge else 0.0
            source_id_hint = 1.0 if str(source.get("source_entity_id") or "").endswith(str(candidate.get("source_entity_id") or "__never__")) else 0.0
            # Existing reviewed candidate evidence is deliberately strong but cannot auto-confirm.
            # Verified work-email equality is the strongest deterministic identity signal.
            relational_score = min(1.0, 0.44 * name + 0.26 * context + 0.10 * source_id_hint + 0.15 * alias + 0.55 * email)
            score = max(explicit_conf, relational_score)
            if score < 0.35 and cid not in explicit:
                continue
            factors = {
                "name_or_alias": round(name, 4),
                "verified_email": round(email, 4),
                "external_alias": round(alias, 4),
                "organizational_context": round(context, 4),
                "source_specific_id": round(source_id_hint, 4),
                "existing_candidate_confidence": round(explicit_conf, 4),
            }
            scored.append({
                "entity": candidate,
                "confidence": round(score, 4),
                "status": str((explicit_edge.properties.get("status") if explicit_edge else None) or "PROPOSED"),
                "factors": factors,
                "graph_paths": context_paths + ([f"{source_record_id}-[:CANDIDATE_MATCH]->{cid}"] if explicit_edge else []),
            })
        scored.sort(key=lambda x: (-x["confidence"], str(x["entity"].get("id"))))
        return {
            "source_record": source,
            "status": "UNRESOLVED" if scored else "NO_CANDIDATE",
            "canonical_entity": None,
            "candidates": scored,
            "auto_merge_performed": False,
        }

    def confirm_match(self, source_record_id: str, entity_id: str, *, confidence: float = 1.0, reviewer_ref: str | None = None) -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        if snapshot.node(source_record_id) is None or snapshot.node(entity_id) is None:
            raise ValueError("Source record and candidate entity must exist")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        at = now_iso()
        props = {"valid_from": at, "confidence": confidence}
        if reviewer_ref:
            props["source_ref_id"] = reviewer_ref
        upsert_relationship(self.client, source_record_id, "REPRESENTS", entity_id, props)
        if any(e.target == entity_id for e in snapshot.edges_from(source_record_id, {"CANDIDATE_MATCH"})):
            upsert_relationship(self.client, source_record_id, "CANDIDATE_MATCH", entity_id, {
                "valid_from": at, "confidence": confidence, "status": "CONFIRMED", **({"source_ref_id": reviewer_ref} if reviewer_ref else {})
            })
        return self.resolve_source_record(source_record_id) or {}
