from __future__ import annotations

import os
from typing import Any

from backend.app.ingestion.adapters.base import FixtureJsonAdapter
from backend.app.ingestion.adapters.http_json import ConfiguredJsonHttpClient
from backend.app.ingestion.models import AdapterPage, SourceConfig, SourceRecordEnvelope
from backend.app.services.phase3_utils import now_iso
from backend.app.ingestion.adapters.base import checksum_payload


class GitHubAdapter(FixtureJsonAdapter):
    source_type = "github"
    adapter_version = "github-v1"

    def __init__(self, config: SourceConfig):
        super().__init__(config)
        self.config = config

    def health_check(self) -> dict[str, Any]:
        if self.config.fixture_path:
            return super().health_check()
        token = os.getenv(str(self.config.settings.get("token_env") or "GITHUB_TOKEN"))
        org = self.config.settings.get("org") or os.getenv("GITHUB_ORG")
        return {"ok": bool(token and org and self.config.base_url), "source_id": self.config.id, "live": True, "configured": bool(token and org)}

    def fetch(self, *, cursor: str | None = None, limit: int = 100) -> AdapterPage:
        if self.config.fixture_path:
            return super().fetch(cursor=cursor, limit=limit)
        token = os.getenv(str(self.config.settings.get("token_env") or "GITHUB_TOKEN"))
        org = self.config.settings.get("org") or os.getenv("GITHUB_ORG")
        if not token or not org or not self.config.base_url:
            raise RuntimeError("GitHub live adapter is not configured")
        client = ConfiguredJsonHttpClient(base_url=self.config.base_url, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"})
        page = int(cursor or "1")
        repos = client.get_json(f"/orgs/{org}/repos", query={"per_page": min(limit, 100), "page": page})
        fetched = now_iso()
        records = []
        for repo in repos[:limit]:
            raw = {"name": repo.get("name"), "full_name": repo.get("full_name"), "html_url": repo.get("html_url"), "owner": (repo.get("owner") or {}).get("login"), "language": repo.get("language")}
            records.append(SourceRecordEnvelope(source_type=self.source_type, source_instance=self.config.source_instance, external_id=str(repo.get("id")), record_type="repository", observed_at=repo.get("updated_at"), fetched_at=fetched, source_updated_at=repo.get("updated_at"), raw_metadata=raw, canonical_source_uri=repo.get("html_url"), cursor=str(page + 1), checksum=checksum_payload(raw)))
        return AdapterPage(records=records, next_cursor=str(page + 1), has_more=len(repos) >= min(limit, 100))
