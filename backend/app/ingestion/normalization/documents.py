from __future__ import annotations

from backend.app.ingestion.models import NormalizedRecord
from backend.app.ingestion.normalization.base import SourceNormalizer
from backend.app.ingestion.normalization.helpers import relation, simple_entity


class DocumentNormalizer(SourceNormalizer):
    source_type = "documents"
    mapping_version = "documents-map-v1"

    def _normalize(self, source_record_id, record):
        raw = record.raw_metadata
        entities, relations, warnings = [], [], []
        observed = record.observed_at or record.source_updated_at or record.fetched_at
        if record.record_type in {"document", "policy_document", "runbook", "architecture_document"}:
            title = raw.get("title") or record.external_id
            entities.append(simple_entity("document", "Document", title, identity={"external_id": record.external_id, "uri": record.canonical_source_uri}, document_type=record.record_type, uri=record.canonical_source_uri, checksum=record.checksum, created_at=observed))
            if record.record_type == "policy_document" or raw.get("policy"):
                p = raw.get("policy") or raw
                policy_id = p.get("policy_id")
                entities.append(simple_entity("policy", "Policy", p.get("name") or title, identity={"business_key": policy_id or title}, canonical_hint=policy_id, status=p.get("status") or "ACTIVE", version=str(p.get("version") or "1"), authoritative=True, requires_owner_approval=bool(p.get("requires_owner_approval", False)), created_at=p.get("created_at") or observed, valid_from=p.get("valid_from") or observed))
                relations.append(relation("policy", "DERIVED_FROM", "document", valid_from=observed))
                scope = p.get("governs") or []
                for idx, target in enumerate(scope):
                    label = target.get("type") or "System"
                    entities.append(simple_entity(f"scope:{idx}", label, target.get("name") or target.get("id"), identity={"business_key": target.get("id") or target.get("name")}, canonical_hint=target.get("canonical_id") or target.get("id")))
                    relations.append(relation("policy", "GOVERNS", f"scope:{idx}", valid_from=target.get("valid_from") or p.get("valid_from") or observed, valid_until=target.get("valid_until"), requires_authoritative_source=True))
                for idx, req in enumerate(p.get("requirements") or []):
                    entities.append(simple_entity(f"requirement:{idx}", "Action", req.get("name") or req.get("code") or f"Requirement {idx+1}", identity={"business_key": req.get("id") or req.get("code")}, canonical_hint=req.get("canonical_id") or req.get("id"), action_type=req.get("action_type") or "verification", status=req.get("status") or "REQUIRED", requirement_code=req.get("code"), created_at=p.get("valid_from") or observed, idempotency_key=req.get("idempotency_key") or f"policy-requirement:{policy_id or title}:{idx}"))
                    relations.append(relation("policy", "REQUIRES", f"requirement:{idx}", valid_from=p.get("valid_from") or observed, requires_authoritative_source=True, required=True))
        else:
            warnings.append(f"UNMAPPED_DOCUMENT_RECORD_TYPE:{record.record_type}")
        return NormalizedRecord(source_record_id=source_record_id, mapping_rule=f"documents:{record.record_type}", mapping_version=self.mapping_version, entities=entities, relations=relations, artifacts=list(record.artifacts), warnings=warnings, trust_metadata=self.trust_metadata())
