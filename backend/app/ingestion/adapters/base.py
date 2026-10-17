from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from backend.app.ingestion.models import AdapterPage, ArtifactPayload, SourceConfig, SourceRecordEnvelope
from backend.app.services.phase3_utils import now_iso
from backend.app.ingestion.credentials import default_credential_store


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def checksum_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def credential_values(config: SourceConfig) -> dict[str, Any]:
    if not getattr(config, "credential_ref", None):
        return {}
    try:
        return default_credential_store().resolve_for_connector(config.credential_ref)
    except KeyError:
        return {}


class SourceAdapter(ABC):
    source_type: str = "generic"
    adapter_version: str = "phase9-v1"

    def __init__(self, config: SourceConfig):
        self.config = config

    @abstractmethod
    def health_check(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def fetch(self, *, cursor: str | None = None, limit: int = 100) -> AdapterPage:
        raise NotImplementedError

    def fetch_incremental(self, *, cursor: str | None = None, limit: int = 100) -> AdapterPage:
        return self.fetch(cursor=cursor, limit=limit)

    def normalize_cursor(self, value: Any) -> str | None:
        return None if value is None else str(value)

    def source_identity(self) -> dict[str, str]:
        return {"source_type": self.source_type, "source_instance": self.config.source_instance}

    def artifact_references(self, record: SourceRecordEnvelope) -> list[ArtifactPayload]:
        return list(record.artifacts)


class FixtureJsonAdapter(SourceAdapter):
    """Deterministic test adapter that consumes realistic source-shaped JSON payloads."""

    source_type = "fixture"

    def _path(self) -> Path:
        if not self.config.fixture_path:
            raise RuntimeError(f"{self.config.id} has no fixture_path")
        return Path(self.config.fixture_path)

    def health_check(self) -> dict[str, Any]:
        path = self._path()
        return {"ok": path.exists(), "source_id": self.config.id, "fixture": str(path), "live": False}

    def _raw_records(self) -> list[dict[str, Any]]:
        path = self._path()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload = payload.get("records", [])
        if not isinstance(payload, list):
            raise ValueError("Fixture payload must be a list or {'records': [...]} object")
        rows = [dict(x) for x in payload]
        selected = [str(x).strip().lower() for x in (self.config.scope_config.get("selected") or []) if str(x).strip()]
        if selected:
            # Scope filtering is deterministic and connector-agnostic for fixture verification.
            # Identity/user rows are retained because scoped records may reference them.
            scoped=[]
            for row in rows:
                haystack=canonical_json(row).lower()
                if row.get("record_type") in {"user","person","identity"} or any(term in haystack for term in selected):
                    scoped.append(row)
            rows=scoped
        return rows

    def fetch(self, *, cursor: str | None = None, limit: int = 100) -> AdapterPage:
        rows = self._raw_records()
        start = int(cursor or 0)
        if start < 0:
            start = 0
        selected = rows[start:start + max(1, limit)]
        fetched_at = now_iso()
        records: list[SourceRecordEnvelope] = []
        for offset, raw in enumerate(selected, start=start):
            payload = dict(raw)
            external_id = str(payload.pop("external_id"))
            record_type = str(payload.pop("record_type"))
            observed_at = payload.pop("observed_at", None)
            source_updated_at = payload.pop("source_updated_at", observed_at)
            version = payload.pop("version", None)
            etag = payload.pop("etag", None)
            canonical_source_uri = payload.pop("canonical_source_uri", None)
            deleted = bool(payload.pop("deleted", False))
            schema_version = str(payload.pop("schema_version", "1"))
            artifact_rows = payload.pop("artifacts", []) or []
            artifacts = [ArtifactPayload(**a) for a in artifact_rows]
            raw_metadata = payload
            checksum = checksum_payload({
                "external_id": external_id,
                "record_type": record_type,
                "observed_at": observed_at,
                "source_updated_at": source_updated_at,
                "version": version,
                "deleted": deleted,
                "schema_version": schema_version,
                "raw_metadata": raw_metadata,
                "artifact_hashes": [checksum_payload(a.model_dump(mode="json")) for a in artifacts],
            })
            records.append(SourceRecordEnvelope(
                source_type=self.source_type,
                source_instance=self.config.source_instance,
                external_id=external_id,
                record_type=record_type,
                observed_at=observed_at,
                fetched_at=fetched_at,
                source_updated_at=source_updated_at,
                version=str(version) if version is not None else None,
                etag=str(etag) if etag is not None else None,
                raw_metadata=raw_metadata,
                canonical_source_uri=canonical_source_uri,
                artifacts=artifacts,
                cursor=str(offset + 1),
                checksum=checksum,
                deleted=deleted,
                schema_version=schema_version,
            ))
        next_index = start + len(selected)
        return AdapterPage(records=records, next_cursor=str(next_index), has_more=next_index < len(rows))
