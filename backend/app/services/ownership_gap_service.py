from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph import phase3_queries
from backend.app.graph.temporal import temporal_sort_key, to_epoch_us
from backend.app.services.phase3_utils import is_active_node, node_dict, now_iso
from backend.app.services.routing_service import ResponsibilityRoutingService


class OwnershipGapService:
    """Detect temporally orphaned or ambiguously owned active resources."""

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.routing = ResponsibilityRoutingService(client)

    @staticmethod
    def _severity(resource: dict[str, Any], dependents: list[dict[str, Any]], reasons: list[str]) -> tuple[str, list[str]]:
        basis: list[str] = []
        criticality = str(resource.get("criticality") or "").upper()
        dependency_criticalities = {str(item.get("criticality") or "").upper() for item in dependents}
        if criticality in {"CRITICAL", "SEV-0", "SEV-1"}:
            basis.append(f"resource criticality={criticality}")
        if dependency_criticalities.intersection({"CRITICAL", "HIGH", "SEV-0", "SEV-1"}):
            basis.append("at least one active dependent marks this dependency high/critical")
        if dependents:
            basis.append(f"{len(dependents)} active dependent system(s) point to the resource")
        if "AMBIGUOUS_SIMULTANEOUS_OWNERS" in reasons:
            basis.append("multiple current formal owners make escalation authority ambiguous")
        if "NO_CURRENT_OWNER" in reasons or "OWNER_ENTITY_INACTIVE" in reasons or "OWNER_RELATIONSHIP_EXPIRED" in reasons:
            basis.append("active resource lacks one unambiguous active formal owner")

        if criticality in {"CRITICAL", "SEV-0", "SEV-1"} or dependency_criticalities.intersection({"CRITICAL", "HIGH", "SEV-0", "SEV-1"}):
            return "CRITICAL", basis
        if dependents:
            return "HIGH", basis
        return "MEDIUM", basis

    def inspect_resource(self, entity_id: str, *, as_of: str | None = None) -> dict[str, Any] | None:
        as_of = as_of or now_iso()
        entity_result = self.client.read(
            "MATCH (s:Entity:System {tenant_id:$tenant_id, id:$id}) RETURN s LIMIT 1",
            {"tenant_id": self.client.settings.tenant_id, "id": entity_id},
        )
        if not entity_result.result_set:
            return None
        resource = node_dict(entity_result.result_set[0][0]) or {}
        if str(resource.get("status") or "").upper() != "ACTIVE" or not is_active_node(resource, as_of):
            return {
                "resource": resource,
                "as_of": as_of,
                "orphaned": False,
                "ambiguous": False,
                "reasons": ["RESOURCE_NOT_ACTIVE"],
                "current_owners": [],
                "historical_owner": None,
                "dependent_systems": [],
                "severity": "NONE",
                "risk_basis": ["Only active resources are evaluated as ownership gaps."],
            }

        owner_info = self.routing.find_owner(entity_id, as_of=as_of)
        current_owners = owner_info["owners"]
        reasons: list[str] = []
        if len(current_owners) == 0:
            reasons.append("NO_CURRENT_OWNER")
            if owner_info["inactive_owner_paths"]:
                reasons.append("OWNER_ENTITY_INACTIVE")
        if len(current_owners) > 1:
            reasons.append("AMBIGUOUS_SIMULTANEOUS_OWNERS")

        history_rows = phase3_queries.ownership_history(self.client, entity_id).result_set
        history: list[dict[str, Any]] = []
        current_owner_ids = {str(item["actor"].get("id")) for item in current_owners}
        for owner, valid_from, valid_until, confidence, authoritative, source_ref_id in history_rows:
            owner_data = node_dict(owner) or {}
            history.append(
                {
                    "actor": owner_data,
                    "valid_from": valid_from,
                    "valid_until": valid_until,
                    "confidence": confidence,
                    "authoritative": bool(authoritative),
                    "source_ref_id": source_ref_id,
                    "path": [owner_data.get("id"), "OWNS", entity_id],
                }
            )
        as_of_us = to_epoch_us(as_of)
        ended_history = [
            item for item in history
            if item.get("valid_until") and to_epoch_us(item["valid_until"]) <= as_of_us
        ]
        if not current_owners and ended_history:
            reasons.append("OWNER_RELATIONSHIP_EXPIRED")

        historical_candidates = [
            item for item in history
            if str(item["actor"].get("id")) not in current_owner_ids
            and (item.get("valid_until") is not None or not is_active_node(item["actor"], as_of))
        ]
        historical_candidates.sort(
            key=lambda item: (
                temporal_sort_key(item.get("valid_until")),
                temporal_sort_key(item.get("valid_from")),
            ),
            reverse=True,
        )
        historical_owner = historical_candidates[0] if historical_candidates else None

        dependents: list[dict[str, Any]] = []
        for dependent, criticality, dependency_kind, confidence, source_ref_id in phase3_queries.current_dependents(
            self.client, entity_id, as_of
        ).result_set:
            dependent_data = node_dict(dependent) or {}
            if not is_active_node(dependent_data, as_of):
                continue
            dependents.append(
                {
                    "system": dependent_data,
                    "criticality": criticality,
                    "dependency_kind": dependency_kind,
                    "confidence": confidence,
                    "source_ref_id": source_ref_id,
                    "path": [dependent_data.get("id"), "DEPENDS_ON", entity_id],
                }
            )

        orphaned = len(current_owners) == 0
        ambiguous = len(current_owners) > 1
        severity, risk_basis = self._severity(resource, dependents, reasons)
        if not orphaned and not ambiguous:
            severity = "NONE"
            risk_basis = ["Exactly one active, temporally valid formal owner exists."]

        return {
            "resource": resource,
            "as_of": as_of,
            "orphaned": orphaned,
            "ambiguous": ambiguous,
            "reasons": reasons,
            "current_owners": current_owners,
            "historical_owner": historical_owner,
            "ownership_history": history,
            "dependent_systems": dependents,
            "severity": severity,
            "risk_basis": risk_basis,
        }

    def detect_orphaned_resources(self, *, as_of: str | None = None) -> dict[str, Any]:
        as_of = as_of or now_iso()
        results: list[dict[str, Any]] = []
        for row in phase3_queries.active_systems(self.client).result_set:
            resource = node_dict(row[0]) or {}
            if not is_active_node(resource, as_of):
                continue
            finding = self.inspect_resource(str(resource.get("id")), as_of=as_of)
            if finding and (finding["orphaned"] or finding["ambiguous"]):
                results.append(finding)
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}
        results.sort(key=lambda item: (severity_order.get(item["severity"], 9), str(item["resource"].get("id"))))
        return {
            "as_of": as_of,
            "count": len(results),
            "resources": results,
        }
