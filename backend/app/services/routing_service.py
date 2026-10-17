from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph import phase3_queries
from backend.app.services.phase3_utils import is_active_node, is_interval_active, node_dict, now_iso


class ResponsibilityRoutingService:
    """Role-preserving organizational routing over current and historical graph relationships."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def find_owner(self, entity_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        as_of = as_of or now_iso()
        owners: list[dict[str, Any]] = []
        inactive_owner_paths: list[dict[str, Any]] = []
        for owner, valid_from, valid_until, confidence, authoritative, source_ref_id in phase3_queries.current_owners(
            self.client, entity_id, as_of
        ).result_set:
            owner_data = node_dict(owner) or {}
            item = {
                "actor": owner_data,
                "role": "FORMAL_OWNER",
                "valid_from": valid_from,
                "valid_until": valid_until,
                "confidence": confidence,
                "authoritative": bool(authoritative),
                "source_ref_id": source_ref_id,
                "path": [owner_data.get("id"), "OWNS", entity_id],
            }
            if is_active_node(owner_data, as_of):
                owners.append(item)
            else:
                item["reason_excluded"] = "owner entity is not active at requested time"
                inactive_owner_paths.append(item)
        return {
            "entity_id": entity_id,
            "as_of": as_of,
            "owners": owners,
            "ambiguous": len(owners) > 1,
            "inactive_owner_paths": inactive_owner_paths,
        }

    def find_responsible_actor(self, entity_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        as_of = as_of or now_iso()
        responsible: list[dict[str, Any]] = []
        for actor, confidence, valid_from, valid_until, source_ref_id in phase3_queries.current_responsibility(
            self.client, entity_id, as_of
        ).result_set:
            actor_data = node_dict(actor) or {}
            if not is_active_node(actor_data, as_of):
                continue
            responsible.append(
                {
                    "actor": actor_data,
                    "role": "RESPONSIBLE_ACTOR",
                    "confidence": confidence,
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                    "source_ref_id": source_ref_id,
                    "path": [actor_data.get("id"), "RESPONSIBLE_FOR", entity_id],
                }
            )
        owner = self.find_owner(entity_id, as_of=as_of)
        return {
            "entity_id": entity_id,
            "as_of": as_of,
            "responsible": responsible,
            "formal_owners": owner["owners"],
            "roles_conflated": False,
        }

    def find_experts(self, entity_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        as_of = as_of or now_iso()
        current: list[dict[str, Any]] = []
        historical: list[dict[str, Any]] = []
        for person, confidence, valid_from, valid_until, source_ref_id in phase3_queries.expertise_history(
            self.client, entity_id
        ).result_set:
            person_data = node_dict(person) or {}
            item = {
                "actor": person_data,
                "confidence": float(confidence or 0.0),
                "valid_from": valid_from,
                "valid_until": valid_until,
                "source_ref_id": source_ref_id,
                "path": [person_data.get("id"), "EXPERT_IN", entity_id],
            }
            if is_interval_active(valid_from, valid_until, as_of) and is_active_node(person_data, as_of):
                item["role"] = "DOMAIN_EXPERT"
                current.append(item)
            else:
                item["role"] = "HISTORICAL_EXPERT"
                historical.append(item)
        current.sort(key=lambda item: (-item["confidence"], str(item["actor"].get("id"))))
        historical.sort(key=lambda item: (-item["confidence"], str(item["actor"].get("id"))))

        experience: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for person, change, path_kind in phase3_queries.historical_experience(self.client, entity_id).result_set:
            person_data = node_dict(person) or {}
            change_data = node_dict(change) or {}
            key = (str(person_data.get("id")), str(change_data.get("id")), str(path_kind))
            if key in seen:
                continue
            seen.add(key)
            experience.append(
                {
                    "actor": person_data,
                    "change": change_data,
                    "role": "HISTORICAL_EXPERIENCE",
                    "path_kind": path_kind,
                    "path": [person_data.get("id"), path_kind, change_data.get("id"), "CHANGED/AFFECTS", entity_id],
                }
            )
        return {
            "entity_id": entity_id,
            "as_of": as_of,
            "current_experts": current,
            "historical_experts": historical,
            "historical_experience": experience,
        }

    def find_approvers(self, entity_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        as_of = as_of or now_iso()
        approvers: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for actor, deployment, change, confidence in phase3_queries.related_approvers(self.client, entity_id, as_of).result_set:
            actor_data = node_dict(actor) or {}
            deployment_data = node_dict(deployment) or {}
            change_data = node_dict(change) or {}
            if not is_active_node(actor_data, as_of):
                continue
            key = (str(actor_data.get("id")), str(deployment_data.get("id")), str(change_data.get("id")))
            if key in seen:
                continue
            seen.add(key)
            approvers.append(
                {
                    "actor": actor_data,
                    "role": "APPROVER",
                    "confidence": confidence,
                    "deployment": deployment_data,
                    "change": change_data,
                    "path": [deployment_data.get("id"), "APPROVED_BY", actor_data.get("id")],
                    "scope_path": [deployment_data.get("id"), "CONTAINS", change_data.get("id"), "CHANGED/AFFECTS", entity_id],
                }
            )
        return {"entity_id": entity_id, "as_of": as_of, "approvers": approvers}

    def rank_candidate_responders(self, entity_id: str, *, as_of: str | None = None) -> dict[str, Any]:
        as_of = as_of or now_iso()
        owner_info = self.find_owner(entity_id, as_of=as_of)
        responsibility_info = self.find_responsible_actor(entity_id, as_of=as_of)
        expert_info = self.find_experts(entity_id, as_of=as_of)
        approver_info = self.find_approvers(entity_id, as_of=as_of)

        candidates: dict[str, dict[str, Any]] = {}

        def add(actor: dict[str, Any], role: str, points: float, path: list[Any], *, basis: str, formal: bool) -> None:
            actor_id = str(actor.get("id") or "")
            if not actor_id:
                return
            entry = candidates.setdefault(
                actor_id,
                {"actor": actor, "score": 0.0, "roles": [], "paths": [], "basis": [], "formal_roles": []},
            )
            entry["score"] += points
            if role not in entry["roles"]:
                entry["roles"].append(role)
            if formal and role not in entry["formal_roles"]:
                entry["formal_roles"].append(role)
            entry["paths"].append(path)
            entry["basis"].append(basis)

        for owner in owner_info["owners"]:
            actor = owner["actor"]
            labels = set(actor.get("_labels", []))
            add(actor, "FORMAL_OWNER", 95.0 if "Team" in labels else 100.0, owner["path"], basis="current OWNS relationship", formal=True)

        for item in responsibility_info["responsible"]:
            add(item["actor"], "RESPONSIBLE_ACTOR", 90.0, item["path"], basis="current RESPONSIBLE_FOR relationship", formal=True)

        for item in expert_info["current_experts"]:
            add(
                item["actor"], "DOMAIN_EXPERT", 80.0 * item["confidence"], item["path"],
                basis="current EXPERT_IN relationship", formal=True,
            )

        for item in approver_info["approvers"]:
            add(item["actor"], "APPROVER", 30.0, item["path"], basis="approval on a change affecting this resource", formal=True)

        for item in expert_info["historical_experts"]:
            add(
                item["actor"], "HISTORICAL_EXPERT", 25.0 * item["confidence"], item["path"],
                basis="expired/historical EXPERT_IN relationship", formal=False,
            )

        for item in expert_info["historical_experience"]:
            add(
                item["actor"], "HISTORICAL_EXPERIENCE", 15.0, item["path"],
                basis="historical change/approval path affecting this resource", formal=False,
            )

        formal_person_ids = {
            str(item["actor"].get("id")) for item in responsibility_info["responsible"] + expert_info["current_experts"]
        }
        for person, team, membership_confidence, ownership_confidence, authoritative in phase3_queries.owner_team_members(
            self.client, entity_id, as_of
        ).result_set:
            person_data = node_dict(person) or {}
            team_data = node_dict(team) or {}
            if not is_active_node(person_data, as_of) or not is_active_node(team_data, as_of):
                continue
            person_id = str(person_data.get("id"))
            role = "OWNER_TEAM_MEMBER" if person_id in formal_person_ids else "BACKUP_CANDIDATE"
            points = 20.0 if role == "OWNER_TEAM_MEMBER" else 12.0
            add(
                person_data,
                role,
                points,
                [person_id, "MEMBER_OF", team_data.get("id"), "OWNS", entity_id],
                basis=(
                    "owner-team membership supplements an existing formal role"
                    if role == "OWNER_TEAM_MEMBER"
                    else "fallback candidate derived from current owner-team membership; not a formal backup designation"
                ),
                formal=False,
            )

        ranked = list(candidates.values())
        for item in ranked:
            item["score"] = round(item["score"], 4)
            item["roles"].sort()
            item["formal_roles"].sort()
        ranked.sort(key=lambda item: (-item["score"], str(item["actor"].get("id"))))
        return {
            "entity_id": entity_id,
            "as_of": as_of,
            "ranked_candidates": ranked,
            "role_semantics": {
                "formal_owner": "OWNS is formal ownership.",
                "responsible_actor": "RESPONSIBLE_FOR is operational accountability, distinct from ownership.",
                "domain_expert": "EXPERT_IN is explicit expertise; team membership alone is not expertise.",
                "historical_expert": "Expired EXPERT_IN remains historical evidence but is not current expertise.",
                "backup_candidate": "Derived fallback from owner-team membership only; it is not asserted as a formal backup.",
                "approver": "APPROVED_BY is approval evidence, not ownership.",
            },
        }
