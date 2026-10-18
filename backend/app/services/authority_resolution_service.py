from __future__ import annotations

from math import prod
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph import phase3_queries
from backend.app.graph.temporal import temporal_sort_key, to_epoch_us
from backend.app.services.claim_memory_service import ClaimMemoryService
from backend.app.services.phase3_utils import is_active_node, node_dict, now_iso


class AuthorityResolutionService:
    """Explainable, rule-based contradiction resolution. No LLM winner selection."""

    MIN_WINNER_SCORE = 35.0
    MIN_WINNER_MARGIN = 8.0
    MIN_SUPPORT_STRENGTH = 0.20

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.memory = ClaimMemoryService(client)

    @staticmethod
    def _combined_strength(items: list[dict[str, Any]]) -> float:
        strengths: list[float] = []
        for item in items:
            relation = float(item.get("relationship", {}).get("confidence") or 0.0)
            evidence = float(item.get("evidence", {}).get("confidence") or 0.0)
            strengths.append(max(0.0, min(1.0, relation * evidence)))
        if not strengths:
            return 0.0
        return 1.0 - prod(1.0 - value for value in strengths)

    @classmethod
    def score_candidate(cls, candidate: dict[str, Any]) -> dict[str, Any]:
        authority = candidate.get("authority_factors", {})
        evidence = candidate.get("evidence_factors", {})
        temporal = candidate.get("temporal_factors", {})
        memory_state = str(candidate.get("memory_state") or "ACTIVE").upper()

        support_strength = float(evidence.get("support_strength") or 0.0)
        refute_strength = float(evidence.get("refute_strength") or 0.0)
        expertise = float(authority.get("expertise_confidence") or 0.0)
        provenance_ratio = float(evidence.get("provenance_ratio") or 0.0)
        authoritative_source_ratio = float(authority.get("authoritative_source_ratio") or 0.0)

        components = {
            "direct_responsibility": 18.0 if authority.get("direct_responsibility") else 0.0,
            "owner_scope": 14.0 if authority.get("owner_scope") else 0.0,
            "expertise": round(12.0 * expertise, 4),
            "approval": 6.0 if authority.get("explicit_approval") else 0.0,
            "authoritative_sources": round(8.0 * authoritative_source_ratio, 4),
            "policy_scope": 5.0 if authority.get("authoritative_policy_scope") else 0.0,
            "supporting_evidence": round(35.0 * support_strength, 4),
            "refuting_evidence": round(-35.0 * refute_strength, 4),
            "provenance": round(3.0 * provenance_ratio + (2.0 if authority.get("actor_attributed") else 0.0), 4),
            "recency": round(4.0 * float(temporal.get("recency_rank") or 0.0), 4),
            "staleness": -35.0 if temporal.get("stale") else 0.0,
        }
        eligible = memory_state not in {"REJECTED", "SUPERSEDED"}
        if not eligible:
            components["state_ineligibility"] = -100.0
        total = round(sum(components.values()), 4)
        return {
            "claim_id": candidate.get("claim", {}).get("id"),
            "eligible": eligible,
            "total_score": total,
            "components": components,
            "support_strength": round(support_strength, 4),
            "refute_strength": round(refute_strength, 4),
        }

    @classmethod
    def resolve_candidates(cls, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        scored = []
        for candidate in candidates:
            score = cls.score_candidate(candidate)
            scored.append({**candidate, "score": score})
        scored.sort(key=lambda item: (-item["score"]["total_score"], str(item.get("claim", {}).get("id") or "")))

        eligible = [item for item in scored if item["score"]["eligible"]]
        if not eligible:
            return {
                "status": "UNRESOLVED",
                "selected_claim_id": None,
                "reason": "No active candidate claim is eligible for authority resolution.",
                "candidates": scored,
            }

        top = eligible[0]
        runner_up = eligible[1] if len(eligible) > 1 else None
        margin = top["score"]["total_score"] - (runner_up["score"]["total_score"] if runner_up else 0.0)
        reasons: list[str] = []
        if top["score"]["total_score"] < cls.MIN_WINNER_SCORE:
            reasons.append(f"top score {top['score']['total_score']:.2f} is below {cls.MIN_WINNER_SCORE:.2f}")
        if runner_up is not None and margin < cls.MIN_WINNER_MARGIN:
            reasons.append(f"winner margin {margin:.2f} is below {cls.MIN_WINNER_MARGIN:.2f}")
        if top["score"]["support_strength"] < cls.MIN_SUPPORT_STRENGTH:
            reasons.append(
                f"support strength {top['score']['support_strength']:.2f} is below {cls.MIN_SUPPORT_STRENGTH:.2f}"
            )
        if top["score"]["refute_strength"] >= top["score"]["support_strength"] and top["score"]["refute_strength"] > 0:
            reasons.append("refuting evidence is at least as strong as supporting evidence")

        if reasons:
            return {
                "status": "UNRESOLVED",
                "selected_claim_id": None,
                "reason": "; ".join(reasons),
                "score_margin": round(margin, 4),
                "candidates": scored,
            }
        return {
            "status": "RESOLVED",
            "selected_claim_id": top.get("claim", {}).get("id"),
            "reason": "A candidate cleared the minimum score, evidence-strength, and score-margin rules.",
            "score_margin": round(margin, 4),
            "candidates": scored,
        }

    def _authority_candidate(self, claim_id: str, as_of: str) -> dict[str, Any]:
        detail = self.memory.get_claim(claim_id)
        if detail is None:
            raise ValueError(f"Claim not found: {claim_id}")

        context_rows = phase3_queries.claim_context_entities(self.client, claim_id).result_set
        contexts: list[dict[str, Any]] = []
        seen_contexts: set[str] = set()
        for row in context_rows:
            context = node_dict(row[0])
            if context and context.get("id") not in seen_contexts:
                seen_contexts.add(str(context.get("id")))
                contexts.append(context)
        context_ids = [str(item["id"]) for item in contexts if item.get("id")]

        responsibility_paths: list[dict[str, Any]] = []
        owner_paths: list[dict[str, Any]] = []
        expertise_paths: list[dict[str, Any]] = []
        approval_paths: list[dict[str, Any]] = []
        actors = detail.get("asserted_by", [])
        for actor in actors:
            actor_id = str(actor.get("id"))
            if not actor_id or not is_active_node(actor, as_of):
                continue
            for _, confidence, ctx in phase3_queries.actor_responsibility_paths(self.client, actor_id, context_ids, as_of).result_set:
                ctx_data = node_dict(ctx) or {}
                responsibility_paths.append(
                    {"actor_id": actor_id, "context_id": ctx_data.get("id"), "confidence": confidence,
                     "path": [actor_id, "RESPONSIBLE_FOR", ctx_data.get("id")]}
                )
            for _, team, confidence, authoritative, ctx in phase3_queries.actor_owner_paths(self.client, actor_id, context_ids, as_of).result_set:
                team_data = node_dict(team) or {}
                ctx_data = node_dict(ctx) or {}
                if not is_active_node(team_data, as_of):
                    continue
                owner_paths.append(
                    {"actor_id": actor_id, "team_id": team_data.get("id"), "context_id": ctx_data.get("id"),
                     "confidence": confidence, "authoritative": bool(authoritative),
                     "path": [actor_id, "MEMBER_OF", team_data.get("id"), "OWNS", ctx_data.get("id")]}
                )
            for _, confidence, ctx in phase3_queries.actor_expertise_paths(self.client, actor_id, context_ids, as_of).result_set:
                ctx_data = node_dict(ctx) or {}
                expertise_paths.append(
                    {"actor_id": actor_id, "context_id": ctx_data.get("id"), "confidence": confidence,
                     "path": [actor_id, "EXPERT_IN", ctx_data.get("id")]}
                )
            for _, approved, path_kind in phase3_queries.actor_approval_paths(self.client, actor_id, context_ids, as_of).result_set:
                approved_data = node_dict(approved) or {}
                approval_paths.append(
                    {"actor_id": actor_id, "approved_id": approved_data.get("id"), "path_kind": path_kind,
                     "path": [approved_data.get("id"), "APPROVED_BY", actor_id]}
                )

        policy_paths: list[dict[str, Any]] = []
        for policy, authoritative, ctx in phase3_queries.governing_policies(self.client, context_ids, as_of).result_set:
            policy_data = node_dict(policy) or {}
            ctx_data = node_dict(ctx) or {}
            if not is_active_node(policy_data, as_of):
                continue
            policy_paths.append(
                {"policy_id": policy_data.get("id"), "context_id": ctx_data.get("id"),
                 "authoritative": bool(authoritative) or bool(policy_data.get("authoritative")),
                 "path": [policy_data.get("id"), "GOVERNS", ctx_data.get("id")]}
            )

        evidence = detail.get("evidence", {"supporting": [], "refuting": []})
        all_evidence = evidence["supporting"] + evidence["refuting"]
        source_nodes: dict[str, dict[str, Any]] = {}
        evidence_with_source = 0
        for item in all_evidence:
            sources = item.get("sources", [])
            if sources:
                evidence_with_source += 1
            for source in sources:
                if source.get("id"):
                    source_nodes[str(source["id"])] = source

        direct_sources = [node_dict(row[0]) for row in phase3_queries.claim_sources(self.client, claim_id).result_set]
        for source in direct_sources:
            if source and source.get("id"):
                source_nodes[str(source["id"])] = source

        authoritative_sources = [source for source in source_nodes.values() if bool(source.get("authoritative"))]
        authoritative_source_ratio = (
            len(authoritative_sources) / len(source_nodes) if source_nodes else 0.0
        )
        provenance_ratio = evidence_with_source / len(all_evidence) if all_evidence else (1.0 if direct_sources else 0.0)

        claim = detail["claim"]
        valid_until = claim.get("valid_until") if claim else None
        stale = detail["memory_state"] in {"SUPERSEDED", "REJECTED"} or bool(
            valid_until and to_epoch_us(valid_until) <= to_epoch_us(as_of)
        )
        expertise_confidence = max((float(path.get("confidence") or 0.0) for path in expertise_paths), default=0.0)

        return {
            "claim": claim,
            "memory_state": detail["memory_state"],
            "asserted_by": actors,
            "contexts": contexts,
            "authority_factors": {
                "actor_attributed": bool(actors),
                "direct_responsibility": bool(responsibility_paths),
                "owner_scope": bool(owner_paths),
                "expertise_confidence": expertise_confidence,
                "explicit_approval": bool(approval_paths),
                "authoritative_source_ratio": authoritative_source_ratio,
                "authoritative_policy_scope": any(path["authoritative"] for path in policy_paths),
            },
            "evidence_factors": {
                "support_strength": self._combined_strength(evidence["supporting"]),
                "refute_strength": self._combined_strength(evidence["refuting"]),
                "supporting_evidence_count": len(evidence["supporting"]),
                "refuting_evidence_count": len(evidence["refuting"]),
                "provenance_ratio": provenance_ratio,
                "authoritative_sources": sorted(authoritative_sources, key=lambda item: str(item.get("id"))),
            },
            "temporal_factors": {
                "created_at": claim.get("created_at") if claim else None,
                "valid_until": valid_until,
                "stale": stale,
                "recency_rank": 0.0,
            },
            "graph_paths": {
                "responsibility": responsibility_paths,
                "ownership": owner_paths,
                "expertise": expertise_paths,
                "approval": approval_paths,
                "policy": policy_paths,
                "evidence": [item.get("path") for item in all_evidence],
                "provenance": [item.get("source_path") for item in all_evidence if item.get("source_path")],
            },
        }

    def resolve_subject_conflicts(self, subject_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        as_of = as_of or now_iso()
        conflict_set = self.memory.get_conflict_set(subject_id)
        claim_ids = sorted({
            conflict[side]
            for conflict in conflict_set["conflicts"]
            for side in ("claim_a_id", "claim_b_id")
        })
        if len(claim_ids) < 2:
            return {
                "subject_id": subject_id,
                "as_of": as_of,
                "status": "UNRESOLVED",
                "selected_claim_id": None,
                "reason": "Fewer than two explicitly contradictory claims are connected to this subject.",
                "candidates": [],
                "conflicts": conflict_set["conflicts"],
            }

        candidates = [self._authority_candidate(claim_id, as_of) for claim_id in claim_ids]
        ordered = sorted(
            candidates,
            key=lambda c: (
                temporal_sort_key((c.get("claim") or {}).get("created_at")),
                (c.get("claim") or {}).get("id") or "",
            ),
        )
        if len(ordered) == 1:
            ordered[0]["temporal_factors"]["recency_rank"] = 1.0
        else:
            denominator = max(1, len(ordered) - 1)
            for index, candidate in enumerate(ordered):
                candidate["temporal_factors"]["recency_rank"] = index / denominator

        resolution = self.resolve_candidates(candidates)
        return {
            "subject_id": subject_id,
            "as_of": as_of,
            "status": resolution["status"],
            "selected_claim_id": resolution["selected_claim_id"],
            "reason": resolution["reason"],
            "score_margin": resolution.get("score_margin"),
            "candidates": resolution["candidates"],
            "conflicts": conflict_set["conflicts"],
            "rule_set": {
                "min_winner_score": self.MIN_WINNER_SCORE,
                "min_winner_margin": self.MIN_WINNER_MARGIN,
                "min_support_strength": self.MIN_SUPPORT_STRENGTH,
                "forced_winner": False,
            },
        }
