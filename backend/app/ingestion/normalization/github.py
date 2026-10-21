from __future__ import annotations

import hashlib
import re
from urllib.parse import quote

from backend.app.ingestion.models import ArtifactType, EntityCandidate, NormalizedRecord
from backend.app.ingestion.normalization.base import SourceNormalizer
from backend.app.ingestion.normalization.helpers import key, person_candidate, relation, simple_entity
from backend.app.services.phase6_utils import stable_id


def _repository_entity(repository: str, uri: str) -> EntityCandidate:
    return EntityCandidate(key="repository", ontology_type="System",
                           canonical_hint=stable_id("SYS-GITHUB-", repository.lower(), length=24),
                           requires_resolution=False, properties={"name": repository,
                           "system_type": "repository", "repository_uri": uri},
                           identity={"business_key": f"github:{repository.lower()}"})


def _sql_file_graph(record):
    from backend.app.ingestion.normalization.postgres_schema import extract_postgres_schema
    raw = record.raw_metadata
    repository, path, commit = (raw.get(k) for k in ("repository", "path", "commit_sha"))
    if (not isinstance(repository, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
            or not isinstance(path, str) or not path.lower().endswith(".sql")
            or not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit)
            or record.version != commit or not record.artifacts or len(record.artifacts) != 1
            or record.artifacts[0].artifact_type != ArtifactType.SOURCE_FILE):
        raise ValueError("SQL file record lacks validated repository, path, commit or SOURCE_FILE artifact")
    artifact = record.artifacts[0]
    expected_uri = f"https://github.com/{repository}/blob/{commit}/{quote(path, safe='/')}"
    if (path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/"))
            or record.canonical_source_uri != expected_uri or raw.get("html_url") != expected_uri
            or artifact.external_uri != expected_uri):
        raise ValueError("SQL file source path or immutable URI is invalid")
    data = artifact.content if isinstance(artifact.content, bytes) else artifact.content.encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    blob_sha = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
    if (digest != raw.get("sha256") or blob_sha != raw.get("blob_sha")
            or len(data) != raw.get("size") or artifact.name != path
            or record.canonical_source_uri != raw.get("html_url")):
        raise ValueError("SQL file artifact does not match its source metadata")

    parsed = extract_postgres_schema(data)
    repo_uri = f"https://github.com/{repository}"
    source = {"source_repository": repository, "source_file_path": path,
              "source_commit_sha": commit, "source_blob_sha": blob_sha,
              "source_file_hash": digest, "source_uri": record.canonical_source_uri}
    entities = [_repository_entity(repository, repo_uri),
                simple_entity("file", "Document", path, canonical_hint=stable_id("DOC-GITHUB-SQL-", repository, path, length=24),
                              identity={"business_key": f"github:{repository}:{path}"}, document_type="sql_dump", **source)]
    relations = [relation("repository", "CONTAINS", "file", **source)]
    for qualified, table in parsed.tables.items():
        table_key = f"table:{qualified}"
        entities.append(simple_entity(table_key, "SqlTable", qualified,
                                      canonical_hint=stable_id("SQL-TABLE-", repository, path, qualified, length=24),
                                      identity={"business_key": f"{repository}:{path}:{qualified}"},
                                      schema_name=table.schema, table_name=table.name, **source))
        relations.append(relation("file", "DEFINES", table_key, **source))
        for column in table.columns.values():
            column_key = f"column:{qualified}:{column.name}"
            entities.append(simple_entity(column_key, "SqlColumn", f"{qualified}.{column.name}",
                                          canonical_hint=stable_id("SQL-COLUMN-", repository, path, qualified, column.name, length=24),
                                          identity={"business_key": f"{repository}:{path}:{qualified}:{column.name}"},
                                          schema_name=table.schema, table_name=table.name, column_name=column.name,
                                          data_type=column.data_type, not_null=column.not_null,
                                          primary_key=column.primary_key, **source))
            relations.append(relation(table_key, "HAS_COLUMN", column_key, **source))
        for constraint in table.constraints:
            constraint_key = f"constraint:{qualified}:{constraint.name or constraint.kind + ':' + ','.join(constraint.columns)}"
            constraint_id = stable_id("SQL-CONSTRAINT-", repository, path, constraint_key, length=24)
            facts = {**source, "constraint_id": constraint_id, "constraint_name": constraint.name,
                     "constraint_type": constraint.kind, "columns": list(constraint.columns),
                     "referenced_table": constraint.referenced_table,
                     "referenced_columns": list(constraint.referenced_columns),
                     "ddl": constraint.ddl, "ddl_line": constraint.line}
            entities.append(simple_entity(constraint_key, "SqlConstraint", constraint.name or constraint_key,
                                          canonical_hint=constraint_id,
                                          identity={"business_key": f"{repository}:{path}:{constraint_key}"},
                                          **facts))
            relations.append(relation(table_key, "HAS_CONSTRAINT", constraint_key, **source,
                                      constraint_id=constraint_id))
            if constraint.kind == "FOREIGN_KEY":
                relations.append(relation(table_key, "FOREIGN_KEY_TO",
                                          f"table:{constraint.referenced_table}", **facts,
                                          source_columns=list(constraint.columns),
                                          target_columns=list(constraint.referenced_columns)))
    return entities, relations, parsed.warnings


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
            if raw.get("full_name") and raw.get("commit_sha"):
                entities.append(_repository_entity(raw["full_name"], raw.get("html_url") or f"https://github.com/{raw['full_name']}"))
            else:
                entities.append(simple_entity("repository", "System", name, identity={"name": name, "aliases": aliases}, canonical_hint=raw.get("canonical_id"), system_type="software_service", repository_uri=raw.get("html_url"), created_at=observed))
        elif rt == "sql_file":
            entities, relations, warnings = _sql_file_graph(record)
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
