from __future__ import annotations

from backend.app.ingestion.models import NormalizedRecord
from backend.app.ingestion.normalization.base import SourceNormalizer
from backend.app.ingestion.normalization.helpers import person_candidate, relation, simple_entity


class JiraNormalizer(SourceNormalizer):
    source_type = "jira"
    mapping_version = "jira-map-v1"

    def _normalize(self, source_record_id, record):
        raw = record.raw_metadata
        entities, relations, warnings = [], [], []
        observed = record.observed_at or record.source_updated_at or record.fetched_at
        rt = record.record_type
        if rt == "user":
            entities.append(person_candidate("subject", name=raw.get("display_name") or raw.get("name"), email=raw.get("email"), username=raw.get("account_id") or raw.get("username"), team_name=raw.get("team"), canonical_hint=raw.get("canonical_id")))
        elif rt == "project":
            name = raw.get("name") or raw.get("key") or record.external_id
            entities.append(simple_entity("project", "Project", name, identity={"name": name, "project_key": raw.get("key")}, canonical_hint=raw.get("canonical_id"), status=raw.get("status") or "ACTIVE", created_at=observed))
        elif rt == "issue":
            issue_key = raw.get("key") or record.external_id
            entities.append(simple_entity("task", "Task", raw.get("summary") or issue_key, identity={"external_id": issue_key}, canonical_hint=raw.get("canonical_id"), status=raw.get("status") or "OPEN", priority=raw.get("priority") or "P2", created_at=raw.get("created_at") or observed, due_at=raw.get("due_date")))
            assignee = raw.get("assignee") or {}
            if assignee:
                entities.append(person_candidate("assignee", name=assignee.get("display_name") or assignee.get("name"), email=assignee.get("email"), username=assignee.get("account_id") or assignee.get("username"), team_name=assignee.get("team"), canonical_hint=assignee.get("canonical_id")))
                relations.append(relation("task", "ASSIGNED_TO", "assignee", valid_from=observed))
            team_name = raw.get("team")
            if team_name:
                entities.append(simple_entity("team", "Team", team_name, identity={"name": team_name}, canonical_hint=raw.get("team_canonical_id"), status="ACTIVE"))
                relations.append(relation("task", "ASSIGNED_TO", "team", valid_from=observed, confidence=0.9))
                if assignee:
                    relations.append(relation("assignee", "MEMBER_OF", "team", valid_from=observed, confidence=0.9))
            system_name = raw.get("system")
            if system_name:
                entities.append(simple_entity("system", "System", system_name, identity={"name": system_name}, canonical_hint=raw.get("system_canonical_id"), system_type="software_service"))
                relations.append(relation("task", "ABOUT", "system", valid_from=observed))
            dependency = raw.get("depends_on")
            if dependency:
                entities.append(simple_entity("dependency_task", "Task", dependency.get("summary") or dependency.get("key") or "Dependency", identity={"external_id": dependency.get("key")}, canonical_hint=dependency.get("canonical_id"), status=dependency.get("status") or "OPEN", created_at=observed))
                relations.append(relation("task", "DEPENDS_ON", "dependency_task", valid_from=observed))
            project = raw.get("project")
            if project:
                entities.append(simple_entity("project", "Project", project.get("name") or project.get("key"), identity={"project_key": project.get("key"), "name": project.get("name")}, canonical_hint=project.get("canonical_id")))
                relations.append(relation("task", "PART_OF", "project", valid_from=observed))
        else:
            warnings.append(f"UNMAPPED_JIRA_RECORD_TYPE:{rt}")
        return NormalizedRecord(source_record_id=source_record_id, mapping_rule=f"jira:{rt}", mapping_version=self.mapping_version, entities=entities, relations=relations, artifacts=list(record.artifacts), warnings=warnings, trust_metadata=self.trust_metadata())
