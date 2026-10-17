from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node
from backend.app.ingestion.adapters.base import SourceAdapter
from backend.app.ingestion.adapters.database import DatabaseAdapter
from backend.app.ingestion.adapters.documents import DocumentAdapter
from backend.app.ingestion.adapters.github import GitHubAdapter
from backend.app.ingestion.adapters.internal_api import InternalApiAdapter
from backend.app.ingestion.adapters.jira import JiraAdapter
from backend.app.ingestion.adapters.slack import SlackAdapter
from backend.app.ingestion.adapters.teams import TeamsAdapter
from backend.app.ingestion.adapters.telemetry import TelemetryAdapter
from backend.app.ingestion.models import SourceConfig, TrustClass
from backend.app.services.phase6_utils import now_iso


ADAPTERS: dict[str, type[SourceAdapter]] = {
    "github": GitHubAdapter,
    "jira": JiraAdapter,
    "slack": SlackAdapter,
    "teams": TeamsAdapter,
    "documents": DocumentAdapter,
    "telemetry": TelemetryAdapter,
    "database": DatabaseAdapter,
    "internal_api": InternalApiAdapter,
}


class SourceRegistry:
    def __init__(self, client: FalkorGraphClient | None = None):
        self.client = client
        self._configs: dict[str, SourceConfig] = {}
        self._adapters: dict[str, SourceAdapter] = {}

    def register(self, config: SourceConfig, *, adapter: SourceAdapter | None = None, persist: bool = True) -> None:
        if config.source_type not in ADAPTERS:
            raise ValueError(f"Unsupported source type: {config.source_type}")
        self._configs[config.id] = config
        self._adapters[config.id] = adapter or ADAPTERS[config.source_type](config)
        if persist and self.client is not None:
            self.persist_source(config)

    def persist_source(self, config: SourceConfig) -> None:
        if self.client is None:
            return
        public = config.public_dict()
        upsert_node(self.client, "DataSource", config.id, {
            "name": config.name,
            "source_type": config.source_type,
            "source_instance": config.source_instance,
            "base_url": config.base_url,
            "trust_class": config.trust_class.value,
            "authoritative_domains": list(config.authoritative_domains),
            "authoritative": config.trust_class == TrustClass.AUTHORITATIVE,
            "enabled": config.enabled,
            "sync_mode": config.sync_mode,
            "adapter_version": config.adapter_version,
            "mapping_version": config.mapping_version,
            "created_at": now_iso(),
            "config_public": str(public),
        })

    def get(self, source_id: str) -> tuple[SourceConfig, SourceAdapter]:
        config = self._configs.get(source_id)
        adapter = self._adapters.get(source_id)
        if config is None or adapter is None:
            raise KeyError(source_id)
        return config, adapter

    def configs(self) -> list[SourceConfig]:
        return [self._configs[k] for k in sorted(self._configs)]

    def public_sources(self) -> list[dict[str, Any]]:
        return [config.public_dict() for config in self.configs()]


def fixture_source_configs(root: Path) -> list[SourceConfig]:
    base = root / "backend" / "tests" / "fixtures" / "ingestion"
    return [
        SourceConfig(id="DS-ING-GITHUB", source_type="github", name="Northstar GitHub", source_instance="northstar-github", trust_class=TrustClass.STRONG, authoritative_domains=["software change", "repository history"], fixture_path=str(base / "github" / "records.json")),
        SourceConfig(id="DS-ING-JIRA", source_type="jira", name="Northstar Jira", source_instance="northstar-jira", trust_class=TrustClass.STANDARD, authoritative_domains=["work tracking"], fixture_path=str(base / "jira" / "records.json")),
        SourceConfig(id="DS-ING-SLACK", source_type="slack", name="Northstar Slack", source_instance="northstar-slack", trust_class=TrustClass.UNTRUSTED, authoritative_domains=[], fixture_path=str(base / "slack" / "records.json")),
        SourceConfig(id="DS-ING-TEAMS", source_type="teams", name="Northstar Teams", source_instance="northstar-teams", trust_class=TrustClass.UNTRUSTED, fixture_path=str(base / "teams" / "records.json")),
        SourceConfig(id="DS-ING-DOCS", source_type="documents", name="Northstar Documentation", source_instance="northstar-docs", trust_class=TrustClass.AUTHORITATIVE, authoritative_domains=["policy"], fixture_path=str(base / "docs" / "records.json")),
        SourceConfig(id="DS-ING-TELEMETRY", source_type="telemetry", name="Northstar Telemetry", source_instance="northstar-telemetry", trust_class=TrustClass.STRONG, authoritative_domains=["runtime observations"], fixture_path=str(base / "telemetry" / "records.json")),
        SourceConfig(id="DS-ING-DATABASE", source_type="database", name="Northstar Read-only Catalog DB", source_instance="northstar-catalog-db", trust_class=TrustClass.AUTHORITATIVE, authoritative_domains=["service ownership", "dependencies"], fixture_path=str(base / "database" / "records.json"), settings={"cursor_column": "id", "auto_validate_ownership": False, "auto_validate_dependencies": False}),
        SourceConfig(id="DS-ING-INTERNAL", source_type="internal_api", name="Northstar Service Catalog API", source_instance="northstar-service-catalog", trust_class=TrustClass.AUTHORITATIVE, authoritative_domains=["service ownership", "dependencies"], fixture_path=str(base / "internal_api" / "records.json"), settings={"auto_validate_ownership": True, "auto_validate_dependencies": True}),
    ]


def build_default_registry(client: FalkorGraphClient | None = None, *, root: Path | None = None, persist: bool = True) -> SourceRegistry:
    root = root or Path(__file__).resolve().parents[3]
    registry = SourceRegistry(client)
    mode = os.getenv("GRAPH_HACKS_INGESTION_MODE", "fixture").lower()
    configs = fixture_source_configs(root)
    if mode == "live":
        # Live endpoints remain server configured. Credentials are environment-only.
        for cfg in configs:
            cfg.fixture_path = None
        for cfg in configs:
            if cfg.source_type == "github":
                cfg.base_url = os.getenv("GITHUB_API_URL", "https://api.github.com")
                cfg.settings.update({"org": os.getenv("GITHUB_ORG"), "token_env": "GITHUB_TOKEN"})
            elif cfg.source_type == "jira":
                cfg.base_url = os.getenv("JIRA_BASE_URL")
                cfg.settings.update({"user_env": "JIRA_EMAIL", "token_env": "JIRA_TOKEN"})
            elif cfg.source_type == "slack":
                cfg.base_url = "https://slack.com/api"
                cfg.settings.update({"channel": os.getenv("SLACK_CHANNEL"), "token_env": "SLACK_BOT_TOKEN"})
            elif cfg.source_type == "internal_api":
                cfg.base_url = os.getenv("INTERNAL_API_BASE_URL")
                cfg.settings.update({"path": os.getenv("INTERNAL_API_PATH", "/records")})
    for cfg in configs:
        registry.register(cfg, persist=persist)
    return registry
