from __future__ import annotations

from backend.app.ingestion.adapters.base import FixtureJsonAdapter


class TelemetryAdapter(FixtureJsonAdapter):
    source_type = "telemetry"
    adapter_version = "telemetry-v1"
