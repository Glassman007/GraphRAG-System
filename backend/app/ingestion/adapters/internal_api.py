from __future__ import annotations

from backend.app.ingestion.adapters.base import FixtureJsonAdapter, checksum_payload, credential_values
from backend.app.ingestion.adapters.http_json import ConfiguredJsonHttpClient
from backend.app.ingestion.models import AdapterPage, SourceRecordEnvelope
from backend.app.services.phase3_utils import now_iso


class InternalApiAdapter(FixtureJsonAdapter):
    source_type = "internal_api"
    adapter_version = "internal-api-v1"

    def health_check(self) -> dict[str, object]:
        if self.config.fixture_path:
            return super().health_check()
        if not self.config.base_url:
            return {"ok": False, "live": True, "message": "Internal API source is not configured"}
        try:
            path = str(self.config.settings.get("path") or "/records")
            headers = dict(self.config.settings.get("headers") or {})
            creds = credential_values(self.config)
            if creds.get("token"):
                headers.setdefault("Authorization", f"Bearer {creds['token']}")
            client = ConfiguredJsonHttpClient(base_url=self.config.base_url, headers=headers)
            client.get_json(path, query={"limit": 1})
            return {"ok": True, "live": True, "message": "Registered internal API is reachable"}
        except PermissionError:
            raise
        except Exception as exc:
            return {"ok": False, "live": True, "message": str(exc)}

    def fetch(self, *, cursor: str | None = None, limit: int = 100) -> AdapterPage:
        if self.config.fixture_path:
            return super().fetch(cursor=cursor, limit=limit)
        if not self.config.base_url:
            raise RuntimeError("Internal API source is not configured")
        path = str(self.config.settings.get("path") or "/records")
        headers = dict(self.config.settings.get("headers") or {})
        creds = credential_values(self.config)
        if creds.get("token"):
            headers.setdefault("Authorization", f"Bearer {creds["token"]}")
        client = ConfiguredJsonHttpClient(base_url=self.config.base_url, headers=headers)
        payload = client.get_json(path, query={"cursor": cursor, "limit": min(limit, 500)})
        rows = payload.get("records", payload if isinstance(payload, list) else [])
        fetched = now_iso()
        records = []
        for row in rows[:limit]:
            ext = str(row.get("external_id") or row.get("id"))
            raw = dict(row)
            records.append(SourceRecordEnvelope(source_type=self.source_type, source_instance=self.config.source_instance, external_id=ext, record_type=str(row.get("record_type") or "record"), observed_at=row.get("observed_at") or row.get("updated_at"), fetched_at=fetched, source_updated_at=row.get("updated_at"), raw_metadata=raw, cursor=str(row.get("cursor") or ext), checksum=checksum_payload(raw)))
        nxt = payload.get("next_cursor") if isinstance(payload, dict) else (records[-1].cursor if records else cursor)
        return AdapterPage(records=records, next_cursor=nxt, has_more=bool(isinstance(payload, dict) and payload.get("has_more")))
