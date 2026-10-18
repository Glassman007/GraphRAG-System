from __future__ import annotations

from backend.app.ingestion.models import NormalizedRecord
from backend.app.ingestion.normalization.base import SourceNormalizer
from backend.app.ingestion.normalization.helpers import key, person_candidate, relation, simple_entity


class GitHubNormalizer(SourceNormalizer):
    source_type = "github"
    mapping_version = "github-map-v1"

    def _normalize(self, source_record_id, record):
        raw = record.raw_metadata
        entities = []
        relations = []
        warnings = []
        rt = record.record_type
        observed = record.observed_at or record.source_updated_at or record.fetched_at

        if rt == "user":
            entities.append(person_candidate(
                "subject",
                name=raw.get("name") or raw.get("display_name") or raw.get("login"),
                email=raw.get("email"),
                username=raw.get("login") or raw.get("username"),
                team_name=raw.get("team"),
                canonical_hint=raw.get("canonical_id"),
            ))
        elif rt == "repository":
            name = raw.get("system_name") or raw.get("name") or raw.get("full_name") or record.external_id
            aliases = [value for value in (raw.get("name"), raw.get("full_name")) if value]
            entities.append(simple_entity("repository", "System", name, identity={"name": name, "aliases": aliases}, canonical_hint=raw.get("canonical_id"), system_type="software_service", repository_uri=raw.get("html_url"), created_at=observed))
        elif rt == "pull_request":
            change_name = raw.get("title") or f"Pull request {raw.get('number') or record.external_id}"
            entities.append(simple_entity("change", "Change", change_name, identity={"external_id": record.external_id, "repository": raw.get("repository")}, canonical_hint=raw.get("canonical_id"), change_type="pull_request", status=raw.get("state") or "UNKNOWN", created_at=raw.get("created_at") or observed, applied_at=raw.get("merged_at")))
            author = raw.get("author") or {}
            if author:
                entities.append(person_candidate("author", name=author.get("name") or author.get("login"), email=author.get("email"), username=author.get("login"), team_name=author.get("team"), canonical_hint=author.get("canonical_id")))
                relations.append(relation("author", "PRODUCED", "change", valid_from=raw.get("created_at") or observed))
            for idx, reviewer in enumerate(raw.get("reviewers") or []):
                entities.append(person_candidate(f"reviewer:{idx}", name=reviewer.get("name") or reviewer.get("login"), email=reviewer.get("email"), username=reviewer.get("login"), team_name=reviewer.get("team"), canonical_hint=reviewer.get("canonical_id")))
            service_name = raw.get("system_name") or raw.get("repository")
            if service_name:
                aliases = [raw.get("repository")] if raw.get("repository") else []
                entities.append(simple_entity("system", "System", service_name, identity={"name": service_name, "aliases": aliases}, canonical_hint=raw.get("system_canonical_id"), system_type="software_service"))
                relations.append(relation("change", "AFFECTS", "system", valid_from=raw.get("merged_at") or observed, confidence=0.9))
            migration_key = raw.get("migration_key")
            if migration_key:
                entities.append(simple_entity("migration", "Change", raw.get("migration_name") or migration_key, identity={"name": raw.get("migration_name") or migration_key, "business_key": migration_key}, canonical_hint=raw.get("migration_canonical_id") or migration_key, change_type="schema_migration", status="DEPLOYED" if raw.get("merged_at") else "PROPOSED", created_at=raw.get("created_at") or observed, applied_at=raw.get("merged_at")))
                relations.append(relation("change", "CONTAINS", "migration", valid_from=raw.get("merged_at") or observed))
                if service_name:
                    relations.append(relation("migration", "AFFECTS", "system", valid_from=raw.get("merged_at") or observed, confidence=0.9))
                if raw.get("database_system"):
                    db = raw["database_system"]
                    entities.append(simple_entity("database", "System", db, identity={"name": db}, canonical_hint=raw.get("database_canonical_id"), system_type="database"))
                    relations.append(relation("migration", "CHANGED", "database", valid_from=raw.get("merged_at") or observed))
        elif rt == "commit":
            entities.append(simple_entity("change", "Change", raw.get("message") or f"Commit {record.external_id}", identity={"external_id": record.external_id}, change_type="commit", status="APPLIED", created_at=observed))
        else:
            warnings.append(f"UNMAPPED_GITHUB_RECORD_TYPE:{rt}")

        return NormalizedRecord(source_record_id=source_record_id, mapping_rule=f"github:{rt}", mapping_version=self.mapping_version, entities=entities, relations=relations, artifacts=list(record.artifacts), warnings=warnings, trust_metadata=self.trust_metadata())
