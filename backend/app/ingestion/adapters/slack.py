from __future__ import annotations

import os
from typing import Any

from backend.app.ingestion.adapters.base import FixtureJsonAdapter, checksum_payload, credential_values
from backend.app.ingestion.adapters.http_json import ConfiguredJsonHttpClient
from backend.app.ingestion.models import AdapterPage, SourceConfig, SourceRecordEnvelope
from backend.app.services.phase3_utils import now_iso


class SlackAdapter(FixtureJsonAdapter):
    source_type = "slack"
    adapter_version = "slack-v1"

    def health_check(self) -> dict[str, Any]:
        if self.config.fixture_path:
            return super().health_check()
        token = credential_values(self.config).get("token") or os.getenv(str(self.config.settings.get("token_env") or "SLACK_BOT_TOKEN"))
        return {"ok": bool(token and self.config.base_url), "source_id": self.config.id, "live": True, "configured": bool(token)}

    def fetch(self, *, cursor: str | None = None, limit: int = 100) -> AdapterPage:
        if self.config.fixture_path:
            return super().fetch(cursor=cursor, limit=limit)
        token = credential_values(self.config).get("token") or os.getenv(str(self.config.settings.get("token_env") or "SLACK_BOT_TOKEN"))
        channel = self.config.settings.get("channel")
        if not token or not channel:
            raise RuntimeError("Slack live adapter is not configured")
        base = self.config.base_url or "https://slack.com/api"
        client = ConfiguredJsonHttpClient(base_url=base, headers={"Authorization": f"Bearer {token}"})
        payload = client.get_json("/conversations.history", query={"channel": channel, "limit": min(limit, 200), "cursor": cursor})
        if not payload.get("ok", False):
            raise RuntimeError(f"Slack API error: {payload.get('error', 'unknown')}")
        fetched = now_iso()
        records = []
        for msg in payload.get("messages", [])[:limit]:
            raw = {"channel": channel, "user_id": msg.get("user"), "text": msg.get("text", ""), "thread_ts": msg.get("thread_ts"), "ts": msg.get("ts")}
            records.append(SourceRecordEnvelope(source_type=self.source_type, source_instance=self.config.source_instance, external_id=str(msg.get("client_msg_id") or msg.get("ts")), record_type="message", observed_at=msg.get("ts"), fetched_at=fetched, source_updated_at=msg.get("ts"), raw_metadata=raw, cursor=(payload.get("response_metadata") or {}).get("next_cursor") or None, checksum=checksum_payload(raw)))
        nxt = (payload.get("response_metadata") or {}).get("next_cursor") or None
        return AdapterPage(records=records, next_cursor=nxt, has_more=bool(nxt))
