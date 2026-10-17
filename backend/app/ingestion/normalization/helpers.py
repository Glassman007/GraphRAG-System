from __future__ import annotations

import re
from typing import Any

from backend.app.ingestion.models import EntityCandidate, RelationCandidate


def key(prefix: str, value: Any) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", str(value or "unknown").strip().lower()).strip("-")
    return f"{prefix}:{clean or 'unknown'}"


def person_candidate(local_key: str, *, name: str | None, email: str | None = None, username: str | None = None, team_name: str | None = None, canonical_hint: str | None = None) -> EntityCandidate:
    props = {"name": name or username or email or "Unknown external user"}
    if email:
        props["email"] = email.lower()
    if username:
        props["username"] = username
    identity = {k: v for k, v in {"email": email.lower() if email else None, "username": username, "name": name, "team_name": team_name}.items() if v}
    return EntityCandidate(key=local_key, ontology_type="Person", properties=props, identity=identity, requires_resolution=True, allow_create=bool(email), canonical_hint=canonical_hint)


def simple_entity(local_key: str, ontology_type: str, name: str, *, identity: dict[str, Any] | None = None, canonical_hint: str | None = None, **props: Any) -> EntityCandidate:
    properties = {"name": name, **{k: v for k, v in props.items() if v is not None}}
    return EntityCandidate(key=local_key, ontology_type=ontology_type, properties=properties, identity=identity or {"name": name}, requires_resolution=ontology_type in {"Person", "Team", "System", "Project"}, allow_create=True, canonical_hint=canonical_hint)


def relation(source_key: str, rel_type: str, target_key: str, *, confidence: float = 1.0, requires_authoritative_source: bool = False, **props: Any) -> RelationCandidate:
    return RelationCandidate(source_key=source_key, rel_type=rel_type, target_key=target_key, confidence=confidence, requires_authoritative_source=requires_authoritative_source, properties={k: v for k, v in props.items() if v is not None})
