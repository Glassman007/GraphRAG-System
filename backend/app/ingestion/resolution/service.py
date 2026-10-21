from __future__ import annotations

import json
import re
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.ingestion.models import EntityCandidate, ResolutionDecision, ResolutionStatus, SourceConfig, TrustClass
from backend.app.services.entity_resolution_service import EntityResolutionService
from backend.app.services.phase4_graph import GraphSnapshot, has_label
from backend.app.services.phase6_utils import now_iso, stable_id


PREFIXES = {
    "Person": "PERSON-EXT-", "Team": "TEAM-EXT-", "System": "SYS-EXT-", "Project": "PROJ-EXT-",
    "Task": "TASK-ING-", "Change": "CHG-ING-", "Document": "DOC-ING-", "Claim": "CLAIM-ING-",
    "Event": "EVT-ING-", "Evidence": "E-ING-", "Policy": "POL-ING-", "Action": "ACT-ING-",
    "Incident": "INC-ING-", "Commitment": "COM-ING-",
}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


class IngestionEntityResolutionService:
    """Thin Phase 9 adapter around the existing Phase 4 entity-resolution capability."""

    AUTO_MATCH_THRESHOLD = 0.92
    REVIEW_THRESHOLD = 0.65

    def __init__(self, client: FalkorGraphClient):
        self.client = client
        self.phase4 = EntityResolutionService(client)

    def _identity_record_id(self, source_record_id: str, entity: EntityCandidate) -> str:
        return stable_id("SRCID-", self.client.settings.tenant_id, source_record_id, entity.key, entity.ontology_type, length=20)

    def _canonical_id(self, entity: EntityCandidate, config: SourceConfig) -> str:
        if entity.canonical_hint:
            return str(entity.canonical_hint)
        identity = entity.identity
        if entity.ontology_type == "Person" and identity.get("email"):
            key = _norm(identity["email"])
        elif identity.get("business_key"):
            key = _norm(identity["business_key"])
        elif identity.get("project_key"):
            key = _norm(identity["project_key"])
        elif identity.get("name"):
            key = _norm(identity["name"])
        elif identity.get("external_id"):
            key = f"{config.id}:{identity['external_id']}"
        else:
            key = f"{config.id}:{entity.key}:{entity.properties.get('name','unknown')}"
        return stable_id(PREFIXES.get(entity.ontology_type, f"{entity.ontology_type.upper()}-ING-"), self.client.settings.tenant_id, key, length=16)

    def _strong_new_identity(self, entity: EntityCandidate, config: SourceConfig, candidates: list[dict[str, Any]]) -> bool:
        if not entity.allow_create:
            return False
        if entity.canonical_hint:
            return True
        if entity.ontology_type == "Person":
            email = _norm(entity.identity.get("email"))
            if not email:
                return False
            # A different verified work email is enough to avoid merging only on name similarity.
            return not any(_norm((c.get("entity") or {}).get("email")) == email for c in candidates)
        if entity.ontology_type in {"Team", "System", "Project"}:
            return config.trust_class in {TrustClass.AUTHORITATIVE, TrustClass.STRONG, TrustClass.STANDARD} and bool(entity.identity.get("name") or entity.identity.get("business_key") or entity.identity.get("project_key"))
        return True

    def _ensure_identity_projection(self, source_record_id: str, entity: EntityCandidate, config: SourceConfig) -> str:
        rid = self._identity_record_id(source_record_id, entity)
        now = now_iso()
        identity = dict(entity.identity)
        # Candidate data is untrusted source content; do not allow it to replace
        # connector-controlled audit/provenance properties below.
        reserved = {"id", "_labels", "name", "source_entity_id", "source_kind", "source_id",
                    "source_instance", "record_type", "candidate_label", "parent_source_record_id",
                    "status", "created_at"}
        identity_props = {k: v for k, v in identity.items() if v is not None and k not in reserved}
        upsert_node(self.client, "SourceRecord", rid, {
            "name": entity.properties.get("name") or identity.get("name") or entity.key,
            "source_entity_id": identity.get("external_id") or identity.get("username") or identity.get("email") or f"{source_record_id}:{entity.key}",
            "source_kind": config.source_type,
            "source_id": config.id,
            "source_instance": config.source_instance,
            "record_type": "identity_projection",
            "candidate_label": entity.ontology_type,
            "parent_source_record_id": source_record_id,
            "status": "ACTIVE",
            "created_at": now,
            **identity_props,
        })
        upsert_relationship(self.client, rid, "DERIVED_FROM", config.id, {"valid_from": now, "confidence": 1.0, "source_ref_id": config.id})
        upsert_relationship(self.client, source_record_id, "REFERENCES", rid, {"valid_from": now, "confidence": 1.0, "source_ref_id": config.id, "reference_kind": "identity_projection"})
        return rid

    def resolve(self, source_record_id: str, entity: EntityCandidate, config: SourceConfig) -> ResolutionDecision:
        snapshot = GraphSnapshot.load(self.client)
        if entity.ontology_type in {"SqlTable", "SqlColumn", "SqlConstraint"} and entity.canonical_hint:
            # Source-qualified schema identities bypass fuzzy matching, but must still
            # report MATCHED when the exact canonical graph node already exists.
            canonical_id = str(entity.canonical_hint)
            existed = snapshot.node(canonical_id) is not None
            return ResolutionDecision(entity_key=entity.key,
                                      status=ResolutionStatus.MATCHED if existed else ResolutionStatus.CREATED,
                                      canonical_id=canonical_id, confidence=1.0,
                                      reasons=["SOURCE_QUALIFIED_SCHEMA_IDENTITY"])
        if entity.canonical_hint and snapshot.node(str(entity.canonical_hint)) is not None:
            cid = str(entity.canonical_hint)
            if entity.requires_resolution:
                identity_record = self._ensure_identity_projection(source_record_id, entity, config)
                self.phase4.confirm_match(identity_record, cid, confidence=1.0, reviewer_ref=source_record_id)
            return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.MATCHED, canonical_id=cid, confidence=1.0, reasons=["CANONICAL_HINT_ALREADY_EXISTS"])

        if not entity.requires_resolution:
            cid = self._canonical_id(entity, config)
            return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.CREATED if snapshot.node(cid) is None else ResolutionStatus.MATCHED, canonical_id=cid, confidence=1.0, reasons=["NON_IDENTITY_ENTITY_DETERMINISTIC_ID"])

        identity_record = self._ensure_identity_projection(source_record_id, entity, config)
        result = self.phase4.resolve_source_record(identity_record) or {}
        if result.get("status") == "CONFIRMED" and result.get("canonical_entity"):
            return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.MATCHED, canonical_id=str(result["canonical_entity"]["id"]), confidence=float(result.get("confidence") or 1.0), reasons=["EXISTING_REPRESENTS"])

        candidates = list(result.get("candidates") or [])
        if candidates:
            top = candidates[0]
            factors = top.get("factors") or {}
            conf = float(top.get("confidence") or 0.0)
            independent = factors.get("verified_email") == 1.0 or factors.get("existing_candidate_confidence", 0) >= self.AUTO_MATCH_THRESHOLD
            margin = conf - float(candidates[1].get("confidence") or 0.0) if len(candidates) > 1 else conf
            if conf >= self.AUTO_MATCH_THRESHOLD and independent and margin >= 0.08:
                cid = str(top["entity"]["id"])
                self.phase4.confirm_match(identity_record, cid, confidence=conf, reviewer_ref=source_record_id)
                return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.MATCHED, canonical_id=cid, confidence=conf, reasons=["PHASE4_HIGH_CONFIDENCE_MATCH"], candidates=candidates)
            if conf >= self.REVIEW_THRESHOLD and not self._strong_new_identity(entity, config, candidates):
                self._quarantine(source_record_id, entity, config, candidates, "AMBIGUOUS_IDENTITY")
                return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.POSSIBLE_MATCH, confidence=conf, reasons=["AMBIGUOUS_IDENTITY"], candidates=candidates)

        if self._strong_new_identity(entity, config, candidates):
            cid = self._canonical_id(entity, config)
            props = dict(entity.properties)
            props.setdefault("created_at", now_iso())
            props.setdefault("status", "ACTIVE")
            upsert_node(self.client, entity.ontology_type, cid, props)
            self.phase4.confirm_match(identity_record, cid, confidence=1.0, reviewer_ref=source_record_id)
            return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.CREATED if snapshot.node(cid) is None else ResolutionStatus.MATCHED, canonical_id=cid, confidence=1.0, reasons=["NEW_CANONICAL_IDENTITY_WITH_STABLE_EVIDENCE"], candidates=candidates)

        self._quarantine(source_record_id, entity, config, candidates, "INSUFFICIENT_IDENTITY_EVIDENCE")
        return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.UNRESOLVED, confidence=float(candidates[0].get("confidence") or 0.0) if candidates else 0.0, reasons=["INSUFFICIENT_IDENTITY_EVIDENCE"], candidates=candidates)


    def preview(self, entity: EntityCandidate, config: SourceConfig) -> ResolutionDecision:
        """Read-only approximation for ingestion dry-run. It never creates SourceRecord/candidate edges."""
        snapshot = GraphSnapshot.load(self.client)
        if entity.canonical_hint and snapshot.node(str(entity.canonical_hint)) is not None:
            return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.MATCHED, canonical_id=str(entity.canonical_hint), confidence=1.0, reasons=["CANONICAL_HINT_ALREADY_EXISTS"])
        if not entity.requires_resolution:
            cid = self._canonical_id(entity, config)
            return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.MATCHED if snapshot.node(cid) else ResolutionStatus.CREATED, canonical_id=cid, confidence=1.0, reasons=["DETERMINISTIC_PREVIEW_ID"])
        candidates = [n for n in snapshot.nodes.values() if has_label(n, entity.ontology_type)]
        email = _norm(entity.identity.get("email"))
        if email:
            exact = [n for n in candidates if _norm(n.get("email")) == email]
            if len(exact) == 1:
                return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.MATCHED, canonical_id=str(exact[0]["id"]), confidence=1.0, reasons=["VERIFIED_EMAIL_PREVIEW_MATCH"])
        name = _norm(entity.identity.get("name") or entity.properties.get("name"))
        exact_name = [n for n in candidates if name and _norm(n.get("name")) == name]
        if len(exact_name) == 1 and entity.ontology_type != "Person":
            return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.MATCHED, canonical_id=str(exact_name[0]["id"]), confidence=0.9, reasons=["UNIQUE_NAME_PREVIEW_MATCH"])
        if self._strong_new_identity(entity, config, []):
            return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.CREATED, canonical_id=self._canonical_id(entity, config), confidence=1.0, reasons=["PREVIEW_NEW_CANONICAL_IDENTITY"])
        return ResolutionDecision(entity_key=entity.key, status=ResolutionStatus.UNRESOLVED, confidence=0.0, reasons=["PREVIEW_INSUFFICIENT_IDENTITY_EVIDENCE"])

    def _quarantine(self, source_record_id: str, entity: EntityCandidate, config: SourceConfig, candidates: list[dict[str, Any]], reason: str) -> str:
        qid = stable_id("QUAR-", source_record_id, entity.key, reason, length=20)
        at = now_iso()
        serial_candidates = [{"entity_id": (c.get("entity") or {}).get("id"), "confidence": c.get("confidence"), "factors": c.get("factors")} for c in candidates[:10]]
        upsert_node(self.client, "IngestionQuarantineRecord", qid, {
            "name": f"Quarantine {source_record_id}:{entity.key}",
            "source_record_id": source_record_id,
            "entity_key": entity.key,
            "candidate_label": entity.ontology_type,
            "identity_projection_id": self._identity_record_id(source_record_id, entity),
            "status": "OPEN",
            "reason": reason,
            "proposed_entity": json.dumps(entity.model_dump(mode="json"), sort_keys=True),
            "candidates": json.dumps(serial_candidates, sort_keys=True),
            "created_at": at,
            "source_ref_id": config.id,
        })
        upsert_relationship(self.client, qid, "DERIVED_FROM", source_record_id, {"valid_from": at, "confidence": 1.0, "source_ref_id": config.id})
        return qid

    def list_quarantine(self, *, status: str | None = None) -> list[dict[str, Any]]:
        snapshot = GraphSnapshot.load(self.client)
        rows = [n for n in snapshot.nodes.values() if has_label(n, "IngestionQuarantineRecord")]
        if status:
            rows = [n for n in rows if n.get("status") == status]
        return sorted(rows, key=lambda x: str(x.get("created_at") or ""), reverse=True)

    def get_quarantine(self, quarantine_id: str) -> dict[str, Any] | None:
        snapshot = GraphSnapshot.load(self.client)
        node = snapshot.node(quarantine_id)
        return node if has_label(node, "IngestionQuarantineRecord") else None

    def resolve_quarantine(self, quarantine_id: str, canonical_id: str, *, reviewer_ref: str = "manual-review") -> dict[str, Any]:
        snapshot = GraphSnapshot.load(self.client)
        q = snapshot.node(quarantine_id)
        if q is None or not has_label(q, "IngestionQuarantineRecord"):
            raise ValueError("Quarantine record not found")
        canonical = snapshot.node(canonical_id)
        if canonical is None:
            raise ValueError("Canonical entity not found")
        expected_label = str(q.get("candidate_label"))
        if not has_label(canonical, expected_label):
            raise ValueError("Canonical entity has the wrong ontology type for this quarantine")
        source_record_id = str(q.get("source_record_id"))
        # A record may contain multiple candidates with the same ontology label.
        # Resolve the exact identity projection, never the first same-label projection.
        projection_id = str(q.get("identity_projection_id") or stable_id(
            "SRCID-", self.client.settings.tenant_id, source_record_id,
            q.get("entity_key"), expected_label, length=20))
        projection = snapshot.node(projection_id)
        referenced = any(e.target == projection_id for e in snapshot.edges_from(source_record_id, {"REFERENCES"}))
        if not (referenced and has_label(projection, "SourceRecord")
                and projection.get("record_type") == "identity_projection"
                and projection.get("candidate_label") == expected_label):
            raise ValueError("Exact identity projection not found for quarantine record")
        self.phase4.confirm_match(projection_id, canonical_id, confidence=1.0, reviewer_ref=reviewer_ref)
        upsert_node(self.client, "IngestionQuarantineRecord", quarantine_id, {"status": "RESOLVED", "resolved_at": now_iso(), "resolved_to": canonical_id, "reviewer_ref": reviewer_ref})
        return self.get_quarantine(quarantine_id) or {}
