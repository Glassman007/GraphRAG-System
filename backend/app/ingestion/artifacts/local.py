from __future__ import annotations

import hashlib
import json
from pathlib import Path

from backend.app.ingestion.artifacts.base import ArtifactStore
from backend.app.ingestion.models import ArtifactMetadata, ArtifactPayload
from backend.app.services.phase6_utils import now_iso


class LocalArtifactStore(ArtifactStore):
    def __init__(self, root: str | Path, *, inline_threshold_bytes: int = 16_384):
        self.root = Path(root)
        self.inline_threshold_bytes = int(inline_threshold_bytes)
        if self.inline_threshold_bytes < 1:
            raise ValueError("inline_threshold_bytes must be positive")
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _bytes(payload: ArtifactPayload) -> bytes:
        return payload.content if isinstance(payload.content, bytes) else payload.content.encode("utf-8")

    def should_externalize(self, payload: ArtifactPayload) -> bool:
        from backend.app.ingestion.models import ArtifactType
        always = {ArtifactType.PDF, ArtifactType.IMAGE, ArtifactType.LOG, ArtifactType.TRACE, ArtifactType.SOURCE_FILE, ArtifactType.ARCHIVE, ArtifactType.DOCUMENT}
        return payload.artifact_type in always or len(self._bytes(payload)) > self.inline_threshold_bytes

    def put(self, payload: ArtifactPayload, *, tenant_id: str, source_type: str, source_record_id: str) -> ArtifactMetadata:
        data = self._bytes(payload)
        digest = hashlib.sha256(data).hexdigest()
        artifact_id = f"ART-{digest[:24].upper()}"
        folder = self.root / tenant_id / source_type / digest[:2] / digest
        folder.mkdir(parents=True, exist_ok=True)
        content_path = folder / "payload.bin"
        if not content_path.exists():
            content_path.write_bytes(data)
        created_at = now_iso()
        meta = ArtifactMetadata(
            artifact_id=artifact_id,
            uri=content_path.resolve().as_uri(),
            sha256=digest,
            size_bytes=len(data),
            mime_type=payload.mime_type,
            artifact_type=payload.artifact_type,
            created_at=created_at,
            source_type=source_type,
            source_record_id=source_record_id,
            retention_class=payload.retention_class,
        )
        meta_path = folder / "metadata.json"
        if not meta_path.exists():
            meta_path.write_text(meta.model_dump_json(indent=2), encoding="utf-8")
        return meta

    def _find_meta(self, artifact_id: str) -> Path | None:
        for path in self.root.glob("*/*/*/*/metadata.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if data.get("artifact_id") == artifact_id:
                return path
        return None

    def get(self, artifact_id: str) -> bytes:
        meta = self._find_meta(artifact_id)
        if meta is None:
            raise KeyError(artifact_id)
        return (meta.parent / "payload.bin").read_bytes()

    def exists(self, artifact_id: str) -> bool:
        return self._find_meta(artifact_id) is not None

    def metadata(self, artifact_id: str) -> ArtifactMetadata | None:
        meta = self._find_meta(artifact_id)
        if meta is None:
            return None
        return ArtifactMetadata.model_validate_json(meta.read_text(encoding="utf-8"))

    def delete_if_safe(self, artifact_id: str) -> bool:
        meta = self._find_meta(artifact_id)
        if meta is None:
            return False
        # Caller is responsible for proving there are no graph references.
        (meta.parent / "payload.bin").unlink(missing_ok=True)
        meta.unlink(missing_ok=True)
        try:
            meta.parent.rmdir()
        except OSError:
            pass
        return True
