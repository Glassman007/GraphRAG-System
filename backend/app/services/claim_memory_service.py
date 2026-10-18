from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_relationship
from backend.app.graph import phase3_queries
from backend.app.graph.temporal import temporal_sort_key
from backend.app.services.phase3_utils import dedupe_nodes, node_dict, now_iso


class ClaimMemoryService:
    """Deterministic conflict-aware organizational memory over FalkorDB."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def _core(self, claim_id: str) -> dict[str, Any] | None:
        result = phase3_queries.claim_core(self.client, claim_id)
        if not result.result_set:
            return None
        claim = node_dict(result.result_set[0][0])
        subjects = dedupe_nodes([node_dict(row[1]) for row in result.result_set])
        actors = dedupe_nodes([node_dict(row[2]) for row in result.result_set])
        return {"claim": claim, "subjects": subjects, "asserted_by": actors}

    def get_claim_evidence(self, claim_id: str) -> dict[str, list[dict[str, Any]]]:
        result = phase3_queries.claim_evidence(self.client, claim_id)
        supporting: dict[str, dict[str, Any]] = {}
        refuting: dict[str, dict[str, Any]] = {}
        for evidence, relation_type, relation_confidence, relation_valid_from, source in result.result_set:
            evidence_data = node_dict(evidence) or {}
            source_data = node_dict(source)
            bucket = supporting if relation_type == "SUPPORTS" else refuting
            evidence_id = str(evidence_data.get("id"))
            item = bucket.setdefault(
                evidence_id,
                {
                    "evidence": evidence_data,
                    "relationship": {
                        "type": relation_type,
                        "confidence": relation_confidence,
                        "valid_from": relation_valid_from,
                    },
                    "sources": [],
                    "path": [evidence_id, relation_type, claim_id],
                },
            )
            if source_data and all(existing.get("id") != source_data.get("id") for existing in item["sources"]):
                item["sources"].append(source_data)
                item["source_path"] = [evidence_id, "DERIVED_FROM", source_data.get("id")]
        return {
            "supporting": list(supporting.values()),
            "refuting": list(refuting.values()),
        }

    def get_claim_history(self, claim_id: str) -> dict[str, Any]:
        core = self._core(claim_id)
        if core is None:
            return {"claim": None, "events": []}

        supersession = phase3_queries.claim_supersession(self.client, claim_id)
        incoming: list[dict[str, Any]] = []
        outgoing: list[dict[str, Any]] = []
        for newer, superseded_at, older, supersedes_at in supersession.result_set:
            newer_data = node_dict(newer)
            older_data = node_dict(older)
            if newer_data and all(x["claim"].get("id") != newer_data.get("id") for x in incoming):
                incoming.append({"claim": newer_data, "at": superseded_at})
            if older_data and all(x["claim"].get("id") != older_data.get("id") for x in outgoing):
                outgoing.append({"claim": older_data, "at": supersedes_at})

        conflicts_result = phase3_queries.claim_conflicts(self.client, claim_id)
        contradictions = []
        for other, scope, confidence, detected_at, source_ref_id in conflicts_result.result_set:
            contradictions.append(
                {
                    "claim": node_dict(other),
                    "scope": scope,
                    "confidence": confidence,
                    "detected_at": detected_at,
                    "source_ref_id": source_ref_id,
                }
            )

        evidence = self.get_claim_evidence(claim_id)
        events: list[dict[str, Any]] = []
        created_at = (core["claim"] or {}).get("created_at")
        if created_at:
            events.append({"type": "CLAIM_RECORDED", "at": created_at, "claim_id": claim_id})
        for item in evidence["supporting"] + evidence["refuting"]:
            ev = item["evidence"]
            events.append(
                {
                    "type": item["relationship"]["type"],
                    "at": item["relationship"].get("valid_from") or ev.get("observed_at"),
                    "evidence_id": ev.get("id"),
                }
            )
        for item in contradictions:
            events.append({"type": "CONTRADICTS", "at": item.get("detected_at"), "other_claim_id": item["claim"].get("id")})
        for item in incoming:
            events.append({"type": "SUPERSEDED_BY", "at": item.get("at"), "claim_id": item["claim"].get("id")})
        for item in outgoing:
            events.append({"type": "SUPERSEDES", "at": item.get("at"), "claim_id": item["claim"].get("id")})
        events.sort(key=lambda item: (temporal_sort_key(item.get("at")), item.get("type") or ""))
        return {
            "claim": core["claim"],
            "superseded_by": incoming,
            "supersedes": outgoing,
            "contradictions": contradictions,
            "events": events,
        }

    @staticmethod
    def normalize_state(raw_status: str | None, *, superseded: bool, has_conflict: bool) -> str:
        status = str(raw_status or "").upper()
        if status == "REJECTED":
            return "REJECTED"
        if superseded or status == "SUPERSEDED":
            return "SUPERSEDED"
        if status == "UNRESOLVED" or (has_conflict and status in {"", "OPEN", "ACTIVE"}):
            return "UNRESOLVED"
        return "ACTIVE"

    def get_claim(self, claim_id: str) -> dict[str, Any] | None:
        core = self._core(claim_id)
        if core is None:
            return None
        history = self.get_claim_history(claim_id)
        evidence = self.get_claim_evidence(claim_id)
        state = self.normalize_state(
            (core["claim"] or {}).get("status"),
            superseded=bool(history["superseded_by"]),
            has_conflict=bool(history["contradictions"]),
        )
        return {
            **core,
            "memory_state": state,
            "evidence": evidence,
            "contradictions": history["contradictions"],
            "supersession": {
                "superseded_by": history["superseded_by"],
                "supersedes": history["supersedes"],
            },
            "history": history["events"],
            "provenance_complete": bool(core["asserted_by"] or evidence["supporting"] or evidence["refuting"]),
        }

    def get_claims_about(self, subject_id: str) -> list[dict[str, Any]]:
        rows = phase3_queries.claims_about(self.client, subject_id).result_set
        return [self.get_claim(node_dict(row[0])["id"]) for row in rows if node_dict(row[0])]

    def get_conflict_set(self, subject_id: str) -> dict[str, Any]:
        raw = phase3_queries.subject_conflicts(self.client, subject_id).result_set
        seen_pairs: set[tuple[str, str]] = set()
        conflicts: list[dict[str, Any]] = []
        claim_ids: set[str] = set()
        for a, b, scope, confidence, detected_at, source_ref_id in raw:
            a_data = node_dict(a) or {}
            b_data = node_dict(b) or {}
            pair = tuple(sorted((str(a_data.get("id")), str(b_data.get("id")))))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            claim_ids.update(pair)
            conflicts.append(
                {
                    "claim_a_id": pair[0],
                    "claim_b_id": pair[1],
                    "scope": scope,
                    "confidence": confidence,
                    "detected_at": detected_at,
                    "source_ref_id": source_ref_id,
                    "path": [pair[0], "CONTRADICTS", pair[1]],
                }
            )
        claims = [self.get_claim(claim_id) for claim_id in sorted(claim_ids)]
        return {
            "subject_id": subject_id,
            "claims": [claim for claim in claims if claim is not None],
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
        }

    def record_contradiction(
        self,
        claim_a_id: str,
        claim_b_id: str,
        *,
        scope: str | None = None,
        confidence: float = 1.0,
        detected_at: str | None = None,
        source_ref_id: str | None = None,
    ) -> dict[str, Any]:
        if claim_a_id == claim_b_id:
            raise ValueError("A claim cannot contradict itself")
        claim_a = self._core(claim_a_id)
        claim_b = self._core(claim_b_id)
        if claim_a is None or claim_b is None:
            raise ValueError("Both claims must already exist")
        subjects_a = {s.get("id") for s in claim_a["subjects"]}
        subjects_b = {s.get("id") for s in claim_b["subjects"]}
        if not subjects_a.intersection(subjects_b):
            raise ValueError("Contradicting claims must share at least one subject")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        props: dict[str, Any] = {
            "valid_from": detected_at or now_iso(),
            "confidence": confidence,
        }
        if scope:
            props["scope"] = scope
        if source_ref_id:
            props["source_ref_id"] = source_ref_id
        upsert_relationship(self.client, claim_a_id, "CONTRADICTS", claim_b_id, props)
        shared_subject = sorted(subjects_a.intersection(subjects_b))[0]
        return self.get_conflict_set(str(shared_subject))
