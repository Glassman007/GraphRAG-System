from __future__ import annotations

from backend.app.ingestion.models import NormalizedRecord
from backend.app.ingestion.normalization.base import SourceNormalizer
from backend.app.ingestion.normalization.helpers import person_candidate, relation, simple_entity
from backend.app.services.phase6_utils import stable_id


class SlackNormalizer(SourceNormalizer):
    source_type = "slack"
    mapping_version = "slack-map-v1"

    def _normalize(self, source_record_id, record):
        raw = record.raw_metadata
        entities, relations, warnings = [], [], []
        observed = record.observed_at or record.source_updated_at or record.fetched_at
        rt = record.record_type
        if rt == "user":
            entities.append(person_candidate("subject", name=raw.get("display_name") or raw.get("real_name"), email=raw.get("email"), username=raw.get("user_id") or raw.get("username"), team_name=raw.get("team"), canonical_hint=raw.get("canonical_id")))
        elif rt == "message":
            author = raw.get("author") or {}
            entities.append(person_candidate("author", name=author.get("display_name") or author.get("name") or raw.get("user_id"), email=author.get("email"), username=author.get("user_id") or raw.get("user_id"), team_name=author.get("team"), canonical_hint=author.get("canonical_id")))
            msg_name = f"Slack message {record.external_id}"
            entities.append(simple_entity("message", "Document", msg_name, identity={"external_id": record.external_id}, document_type="slack_message", uri=record.canonical_source_uri, created_at=observed, excerpt=str(raw.get("text") or "")[:500]))
            relations.append(relation("author", "PRODUCED", "message", valid_from=observed, confidence=1.0))
            assertion = raw.get("assertion")
            if assertion:
                claim_key = stable_id("CLAIM-ING-", self.config.source_instance, record.external_id, assertion)
                entities.append(simple_entity("claim", "Claim", assertion[:120], identity={"external_id": claim_key}, canonical_hint=raw.get("claim_canonical_id"), statement=assertion, status="UNVERIFIED", confidence=float(raw.get("confidence") or 0.5), assertion_kind="source_assertion", created_at=observed))
                relations.append(relation("claim", "ASSERTED_BY", "author", valid_from=observed))
                target = raw.get("about_system") or raw.get("about_incident")
                if target:
                    label = "System" if raw.get("about_system") else "Incident"
                    entities.append(simple_entity("subject", label, target, identity={"name": target}, canonical_hint=raw.get("about_canonical_id")))
                    relations.append(relation("claim", "ABOUT", "subject", valid_from=observed, confidence=0.8))
        else:
            warnings.append(f"UNMAPPED_SLACK_RECORD_TYPE:{rt}")
        return NormalizedRecord(source_record_id=source_record_id, mapping_rule=f"slack:{rt}", mapping_version=self.mapping_version, entities=entities, relations=relations, artifacts=list(record.artifacts), warnings=warnings, trust_metadata=self.trust_metadata())
