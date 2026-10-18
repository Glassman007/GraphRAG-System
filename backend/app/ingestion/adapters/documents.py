from __future__ import annotations

from backend.app.ingestion.adapters.base import FixtureJsonAdapter


class DocumentAdapter(FixtureJsonAdapter):
    source_type = "documents"
    adapter_version = "documents-v1"
