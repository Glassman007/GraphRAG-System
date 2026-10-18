from __future__ import annotations

import base64
import os
from typing import Any

from backend.app.ingestion.adapters.base import FixtureJsonAdapter, checksum_payload, credential_values
from backend.app.ingestion.adapters.http_json import ConfiguredJsonHttpClient
from backend.app.ingestion.models import AdapterPage, SourceConfig, SourceRecordEnvelope
from backend.app.services.phase3_utils import now_iso


class JiraAdapter(FixtureJsonAdapter):
    source_type = "jira"
    adapter_version = "jira-v1"

    def health_check(self) -> dict[str, Any]:
        if self.config.fixture_path:
            return super().health_check()
        creds = credential_values(self.config)
        user = creds.get("username") or creds.get("email") or os.getenv(str(self.config.settings.get("user_env") or "JIRA_EMAIL")) or os.getenv("JIRA_USER")
        token = creds.get("token") or os.getenv(str(self.config.settings.get("token_env") or "JIRA_TOKEN"))
        return {"ok": bool(self.config.base_url and user and token), "source_id": self.config.id, "live": True, "configured": bool(user and token)}

    def fetch(self, *, cursor: str | None = None, limit: int = 100) -> AdapterPage:
        if self.config.fixture_path:
            return super().fetch(cursor=cursor, limit=limit)
        creds = credential_values(self.config)
        user = creds.get("username") or creds.get("email") or os.getenv(str(self.config.settings.get("user_env") or "JIRA_EMAIL")) or os.getenv("JIRA_USER")
        token = creds.get("token") or os.getenv(str(self.config.settings.get("token_env") or "JIRA_TOKEN"))
        if not self.config.base_url or not user or not token:
            raise RuntimeError("Jira live adapter is not configured")
        auth = base64.b64encode(f"{user}:{token}".encode()).decode()
        client = ConfiguredJsonHttpClient(base_url=self.config.base_url, headers={"Authorization": f"Basic {auth}", "Accept": "application/json"})
        start = int(cursor or 0)
        selected=[str(x) for x in (self.config.scope_config.get("selected") or []) if str(x).replace("-","").replace("_","").isalnum()]
        jql=self.config.settings.get("jql")
        if not jql and selected:
            jql="project in (" + ",".join(f'\"{x}\"' for x in selected) + ") order by updated asc"
        payload = client.get_json("/rest/api/3/search", query={"startAt": start, "maxResults": min(limit, 100), "jql": jql or "order by updated asc"})
        fetched = now_iso()
        records = []
        for issue in payload.get("issues", [])[:limit]:
            fields = issue.get("fields") or {}
            raw = {"key": issue.get("key"), "summary": fields.get("summary"), "status": (fields.get("status") or {}).get("name"), "priority": (fields.get("priority") or {}).get("name"), "assignee": fields.get("assignee"), "reporter": fields.get("reporter"), "labels": fields.get("labels") or [], "updated": fields.get("updated"), "duedate": fields.get("duedate")}
            records.append(SourceRecordEnvelope(source_type=self.source_type, source_instance=self.config.source_instance, external_id=str(issue.get("id") or issue.get("key")), record_type="issue", observed_at=fields.get("updated"), fetched_at=fetched, source_updated_at=fields.get("updated"), raw_metadata=raw, canonical_source_uri=f"{self.config.base_url}/browse/{issue.get('key')}", cursor=str(start + len(records) + 1), checksum=checksum_payload(raw)))
        next_cursor = start + len(records)
        return AdapterPage(records=records, next_cursor=str(next_cursor), has_more=next_cursor < int(payload.get("total") or 0))
