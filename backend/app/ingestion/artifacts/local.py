from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from backend.app.ingestion.artifacts.base import DEFAULT_INLINE_THRESHOLD_BYTES, ArtifactStore, payload_bytes
from backend.app.ingestion.models import ArtifactMetadata, ArtifactPayload

PAYLOAD_FILE = "payload.bin"
METADATA_FILE = "metadata.json"
INDEX_DIR = "_index"
_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]")
_ARTIFACT_ID = re.compile(r"^ART-[0-9A-F]{24}$")


def _segment(value: str) -> str:
    cleaned = _UNSAFE.sub("_", value).strip(".") or "_"
    return cleaned[:96]


class LocalArtifactStore(ArtifactStore):
    """Deterministic filesystem ArtifactStore.

    Layout: <root>/<tenant>/<source_type>/<sha[:2]>/<sha>/{payload.bin,metadata.json}
    plus <root>/_index/<artifact_id>.json pointing at the payload directory.
    The artifact id is derived from tenant + source type + sha256, so reingesting identical
    content reuses the same physical object.
    """

    def __init__(self, root: str | os.PathLike[str], *, inline_threshold_bytes: int = DEFAULT_INLINE_THRESHOLD_BYTES):
        super().__init__(inline_threshold_bytes=inline_threshold_bytes)
        self.root = Path(root)

    @staticmethod
    def artifact_id_for(tenant_id: str, source_type: str, sha256: str) -> str:
        digest = hashlib.sha256(f"{tenant_id}|{source_type}|{sha256}".encode("utf-8")).hexdigest()[:24].upper()
        return f"ART-{digest}"

    def _index_path(self, artifact_id: str) -> Path | None:
        if not _ARTIFACT_ID.match(artifact_id):
            return None
        return self.root / INDEX_DIR / f"{artifact_id}.json"

    def _directory(self, artifact_id: str) -> Path | None:
        index = self._index_path(artifact_id)
        if index is None or not index.is_file():
            return None
        relative = json.loads(index.read_text(encoding="utf-8"))["path"]
        directory = (self.root / relative).resolve()
        if self.root.resolve() not in directory.parents:
            return None
        return directory

    def put(self, payload: ArtifactPayload, *, tenant_id: str, source_type: str, source_record_id: str) -> ArtifactMetadata:
        data = payload_bytes(payload)
        sha = hashlib.sha256(data).hexdigest()
        artifact_id = self.artifact_id_for(tenant_id, source_type, sha)
        relative = Path(_segment(tenant_id)) / _segment(source_type) / sha[:2] / sha
        directory = self.root / relative
        existing = self.metadata(artifact_id)
        if existing is not None and (directory / PAYLOAD_FILE).is_file():
            return existing

        directory.mkdir(parents=True, exist_ok=True)
        payload_path = directory / PAYLOAD_FILE
        tmp = payload_path.with_suffix(".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, payload_path)

        meta = ArtifactMetadata(
            artifact_id=artifact_id,
            uri=payload_path.resolve().as_uri(),
            sha256=sha,
            size_bytes=len(data),
            mime_type=payload.mime_type,
            artifact_type=payload.artifact_type,
            created_at=datetime.now(timezone.utc).isoformat(),
            source_type=source_type,
            source_record_id=source_record_id,
            retention_class=payload.retention_class,
        )
        (directory / METADATA_FILE).write_text(json.dumps(meta.model_dump(mode="json"), indent=2, sort_keys=True), encoding="utf-8")
        index = self.root / INDEX_DIR / f"{artifact_id}.json"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(json.dumps({"path": relative.as_posix()}), encoding="utf-8")
        return meta

    def get(self, artifact_id: str) -> bytes:
        directory = self._directory(artifact_id)
        if directory is None or not (directory / PAYLOAD_FILE).is_file():
            raise KeyError(f"Artifact not found: {artifact_id}")
        data = (directory / PAYLOAD_FILE).read_bytes()
        meta = self.metadata(artifact_id)
        if meta is not None and hashlib.sha256(data).hexdigest() != meta.sha256:
            raise ValueError(f"Artifact integrity check failed: {artifact_id}")
        return data

    def exists(self, artifact_id: str) -> bool:
        directory = self._directory(artifact_id)
        return directory is not None and (directory / PAYLOAD_FILE).is_file()

    def metadata(self, artifact_id: str) -> ArtifactMetadata | None:
        directory = self._directory(artifact_id)
        if directory is None or not (directory / METADATA_FILE).is_file():
            return None
        return ArtifactMetadata.model_validate_json((directory / METADATA_FILE).read_text(encoding="utf-8"))

    def delete_if_safe(self, artifact_id: str) -> bool:
        """Remove the physical payload. Callers own the graph-side reference check."""
        directory = self._directory(artifact_id)
        if directory is None:
            return False
        shutil.rmtree(directory, ignore_errors=True)
        index = self._index_path(artifact_id)
        if index is not None:
            index.unlink(missing_ok=True)
        return True
