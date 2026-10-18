from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class CredentialStore:
    """Server-side credential abstraction. Secret values never enter FalkorDB."""

    provider = "local-protected"

    def put(self, tenant_id: str, source_id: str, values: dict[str, Any]) -> str:
        raise NotImplementedError

    def delete(self, credential_ref: str) -> None:
        raise NotImplementedError

    def exists(self, credential_ref: str) -> bool:
        raise NotImplementedError

    def metadata(self, credential_ref: str) -> dict[str, Any]:
        raise NotImplementedError

    def resolve_for_connector(self, credential_ref: str | None) -> dict[str, Any]:
        raise NotImplementedError


class LocalCredentialStore(CredentialStore):
    """Development credential store backed by a chmod-0600 JSON file.

    This is deliberately replaceable by Vault/cloud secret managers. The graph stores
    only the opaque ``credential_ref``. Production deployments should point
    ``GRAPH_HACKS_CREDENTIAL_ROOT`` at protected server storage or replace this class.
    """

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.getenv("GRAPH_HACKS_CREDENTIAL_ROOT") or ".graphhacks_credentials")
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    def _path(self, tenant_id: str) -> Path:
        safe = "".join(ch for ch in tenant_id if ch.isalnum() or ch in "-_") or "tenant"
        return self.root / f"{safe}.json"

    def _load(self, tenant_id: str) -> dict[str, Any]:
        path = self._path(tenant_id)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, tenant_id: str, data: dict[str, Any]) -> None:
        path = self._path(tenant_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _parse(ref: str) -> tuple[str, str]:
        prefix = "secret://local/"
        if not ref.startswith(prefix):
            raise KeyError(ref)
        rest = ref[len(prefix):]
        tenant, _, source = rest.partition("/")
        if not tenant or not source:
            raise KeyError(ref)
        return tenant, source

    def put(self, tenant_id: str, source_id: str, values: dict[str, Any]) -> str:
        cleaned = {str(k): v for k, v in values.items() if v not in (None, "")}
        data = self._load(tenant_id)
        data[source_id] = cleaned
        self._save(tenant_id, data)
        return f"secret://local/{tenant_id}/{source_id}"

    def delete(self, credential_ref: str) -> None:
        tenant, source = self._parse(credential_ref)
        data = self._load(tenant)
        data.pop(source, None)
        self._save(tenant, data)

    def exists(self, credential_ref: str) -> bool:
        try:
            tenant, source = self._parse(credential_ref)
        except KeyError:
            return False
        return source in self._load(tenant)

    def metadata(self, credential_ref: str) -> dict[str, Any]:
        tenant, source = self._parse(credential_ref)
        values = self._load(tenant).get(source)
        if values is None:
            return {"configured": False, "provider": self.provider}
        return {"configured": True, "provider": self.provider, "fields": sorted(values)}

    def resolve_for_connector(self, credential_ref: str | None) -> dict[str, Any]:
        if not credential_ref:
            return {}
        tenant, source = self._parse(credential_ref)
        values = self._load(tenant).get(source)
        if values is None:
            raise KeyError(credential_ref)
        return dict(values)


def default_credential_store() -> LocalCredentialStore:
    return LocalCredentialStore()
