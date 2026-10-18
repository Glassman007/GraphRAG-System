from __future__ import annotations

from backend.app.ingestion.adapters.base import FixtureJsonAdapter


class TeamsAdapter(FixtureJsonAdapter):
    """Microsoft Teams adapter boundary. Fixture-verified; live Microsoft Graph auth is intentionally externalized."""
    source_type = "teams"
    adapter_version = "teams-v1"
