"""Focused PostgreSQL dump extraction and GitHub normalization tests."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from backend.app.ingestion.models import ArtifactPayload, ArtifactType, SourceConfig, SourceRecordEnvelope
from backend.app.ingestion.normalization.github import GitHubNormalizer
from backend.app.ingestion.normalization.postgres_schema import extract_postgres_schema

SQL = b"""CREATE TABLE public.parent (
    id integer PRIMARY KEY
);
CREATE TABLE public.child (
    id integer NOT NULL,
    parent_id integer,
    CONSTRAINT child_pkey PRIMARY KEY (id)
);
COPY public.child (id, parent_id) FROM stdin;
CREATE TABLE public.fake (
);
\\.
ALTER TABLE ONLY public.child
    ADD CONSTRAINT child_parent_fkey FOREIGN KEY (parent_id) REFERENCES public.parent(id);
"""
REPO = "example/sample"
COMMIT = "a" * 40
PATH = "schema.sql"
URL = f"https://github.com/{REPO}/blob/{COMMIT}/{PATH}"


def file_record(content=SQL):
    sha = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
    raw = {"repository": REPO, "path": PATH, "commit_sha": COMMIT,
           "blob_sha": sha, "size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "html_url": URL}
    return SourceRecordEnvelope(source_type="github", source_instance="test",
                                external_id=f"{REPO}:{PATH}", record_type="sql_file",
                                fetched_at="2026-10-21T00:00:00Z", version=COMMIT,
                                raw_metadata=raw, canonical_source_uri=URL,
                                artifacts=[ArtifactPayload(name=PATH, content=content,
                                                           artifact_type=ArtifactType.SOURCE_FILE, external_uri=URL)],
                                checksum="test")


def normalizer():
    return GitHubNormalizer(SourceConfig(id="GH", source_type="github", name="test", source_instance="test"))


def test_postgres_extraction_skips_copy_rows_and_reads_inline_and_alter_constraints():
    schema = extract_postgres_schema(SQL)
    assert set(schema.tables) == {"public.parent", "public.child"}
    assert len(schema.foreign_keys) == 1
    source, fk = schema.foreign_keys[0]
    assert (source, fk.name, fk.columns, fk.referenced_table, fk.referenced_columns) == (
        "public.child", "child_parent_fkey", ("parent_id",), "public.parent", ("id",))
    assert schema.tables["public.parent"].columns["id"].primary_key
    assert schema.tables["public.child"].columns["id"].primary_key
    assert schema.tables["public.child"].columns["id"].not_null
    assert schema.tables["public.child"].columns["parent_id"].data_type == "integer"
    assert not schema.warnings


def test_sql_file_normalizes_to_connected_domain_graph_and_is_deterministic():
    first = normalizer().normalize("SRC-1", file_record())
    second = normalizer().normalize("SRC-1", file_record())
    labels = [e.ontology_type for e in first.entities]
    assert labels.count("System") == 1
    assert labels.count("Document") == 1
    assert labels.count("SqlTable") == 2
    assert labels.count("SqlColumn") == 3
    assert labels.count("SqlConstraint") == 3
    assert [e.canonical_hint for e in first.entities] == [e.canonical_hint for e in second.entities]
    assert {r.rel_type for r in first.relations} == {"CONTAINS", "DEFINES", "HAS_COLUMN", "HAS_CONSTRAINT", "FOREIGN_KEY_TO"}
    fk = next(r for r in first.relations if r.rel_type == "FOREIGN_KEY_TO")
    assert fk.source_key == "table:public.child" and fk.target_key == "table:public.parent"
    assert fk.properties["constraint_name"] == "child_parent_fkey"
    assert fk.properties["source_commit_sha"] == COMMIT and fk.properties["source_file_hash"] == hashlib.sha256(SQL).hexdigest()
    assert first.artifacts[0].content == SQL and first.warnings == []


def test_sql_file_rejects_missing_or_tampered_source_artifact():
    record = file_record()
    record.artifacts = []
    with pytest.raises(ValueError, match="SOURCE_FILE"):
        normalizer().normalize("SRC-1", record)
    record = file_record()
    record.artifacts[0].content = b"tampered"
    with pytest.raises(ValueError, match="does not match"):
        normalizer().normalize("SRC-1", record)


def test_copy_data_must_terminate_before_schema_extraction():
    with pytest.raises(ValueError, match="unterminated COPY"):
        extract_postgres_schema(SQL.split(b"\\.")[0])


def test_chinook_constraint_links_point_to_declarations_in_pinned_raw_file():
    content = (Path(__file__).parent / "fixtures" / "chinook_postgresql_4a944a94.sql").read_bytes()
    assert hashlib.sha256(content).hexdigest() == "e3fde5c1a5b51a2a91429a702c9ca6e69ba56e6c7f5e112724d70c3d03db695e"
    lines = content.decode("utf-8-sig").splitlines()
    declarations = {}
    for number, source_line in enumerate(lines, 1):
        match = re.search(r"\b(?:ADD\s+)?CONSTRAINT\s+(\w+)\s+(PRIMARY\s+KEY|FOREIGN\s+KEY)\b", source_line, re.I)
        if match:
            declarations[match.group(1)] = (number, "PRIMARY_KEY" if match.group(2).upper().startswith("PRIMARY") else "FOREIGN_KEY")
        else:
            # The pinned file places the FK type on the next line.
            match = re.search(r"\bALTER\s+TABLE\s+\w+\s+ADD\s+CONSTRAINT\s+(\w+)\s*$", source_line, re.I)
            if match and number < len(lines) and re.search(r"\bFOREIGN\s+KEY\b", lines[number], re.I):
                declarations[match.group(1)] = (number, "FOREIGN_KEY")
    assert sum(kind == "FOREIGN_KEY" for _, kind in declarations.values()) == 11
    assert sum(kind == "PRIMARY_KEY" for _, kind in declarations.values()) == 11
    assert declarations["invoice_line_pkey"] == (115, "PRIMARY_KEY")
    assert declarations["invoice_line_invoice_id_fkey"] == (182, "FOREIGN_KEY")
    assert declarations["invoice_line_track_id_fkey"] == (187, "FOREIGN_KEY")

    pinned_record = file_record(content)
    pinned_record.raw_metadata.update(repository="lerocha/chinook-database",
                                      path="ChinookDatabase/DataSources/Chinook_PostgreSql.sql",
                                      commit_sha="4a944a942426e1f3263fe539155fb7ef92b04b4a")
    pinned_record.version = pinned_record.raw_metadata["commit_sha"]
    pinned_record.artifacts[0].name = pinned_record.raw_metadata["path"]
    pinned_record.canonical_source_uri = (
        "https://github.com/lerocha/chinook-database/blob/4a944a942426e1f3263fe539155fb7ef92b04b4a/"
        "ChinookDatabase/DataSources/Chinook_PostgreSql.sql")
    pinned_record.raw_metadata["html_url"] = pinned_record.canonical_source_uri
    pinned_record.artifacts[0].external_uri = pinned_record.canonical_source_uri
    normalized = normalizer().normalize("SRC-1", pinned_record)
    constraints = [entity for entity in normalized.entities if entity.ontology_type == "SqlConstraint"]
    assert len(constraints) == 22
    assert {entity.properties["constraint_name"] for entity in constraints} == set(declarations)
    for entity in constraints:
        facts = entity.properties
        number, kind = declarations[facts["constraint_name"]]
        assert (facts["ddl_line"], facts["constraint_type"]) == (number, kind)
        assert facts["source_uri"] == pinned_record.canonical_source_uri
        assert f'{facts["source_uri"]}#L{facts["ddl_line"]}' == f"{pinned_record.canonical_source_uri}#L{number}"
        assert facts["constraint_name"] in lines[number - 1]
    for edge in (edge for edge in normalized.relations if edge.rel_type == "FOREIGN_KEY_TO"):
        assert edge.properties["ddl_line"] == declarations[edge.properties["constraint_name"]][0]
