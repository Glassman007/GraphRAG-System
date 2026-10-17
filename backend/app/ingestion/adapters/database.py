from __future__ import annotations

from typing import Any, Callable

from backend.app.ingestion.adapters.base import FixtureJsonAdapter, checksum_payload, credential_values
from backend.app.ingestion.models import AdapterPage, SourceConfig, SourceRecordEnvelope
from backend.app.services.phase3_utils import now_iso


class DatabaseAdapter(FixtureJsonAdapter):
    """Read-only configured relational ingestion. Live PostgreSQL uses optional psycopg when configured."""
    source_type = "database"
    adapter_version = "database-v1"

    def __init__(self, config: SourceConfig, *, row_provider: Callable[[str | None, int], list[dict[str, Any]]] | None = None):
        super().__init__(config)
        self.row_provider = row_provider

    def health_check(self) -> dict[str, Any]:
        if self.config.fixture_path:
            return super().health_check()
        creds = credential_values(self.config)
        return {"ok": bool(self.row_provider or creds.get("dsn") or self.config.settings.get("dsn_env")), "source_id": self.config.id, "live": True, "read_only": True}

    def fetch(self, *, cursor: str | None = None, limit: int = 100) -> AdapterPage:
        if self.config.fixture_path:
            return super().fetch(cursor=cursor, limit=limit)
        rows: list[dict[str, Any]]
        if self.row_provider:
            rows = self.row_provider(cursor, limit)
        else:
            import os
            try:
                import psycopg  # type: ignore
            except ImportError as exc:
                raise RuntimeError("Live PostgreSQL ingestion requires optional psycopg") from exc
            dsn = credential_values(self.config).get("dsn") or os.getenv(str(self.config.settings.get("dsn_env") or "INGESTION_DATABASE_DSN"))
            query = self.config.settings.get("query")
            cursor_column = self.config.settings.get("cursor_column")
            if not dsn or not query or not cursor_column:
                raise RuntimeError("Database source requires configured DSN env, fixed query and cursor_column")
            # Query text comes only from server-side SourceConfig. Public APIs cannot supply SQL.
            with psycopg.connect(dsn, autocommit=True) as conn:
                with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute(query, {"cursor": cursor, "limit": limit})
                    rows = [dict(r) for r in cur.fetchall()]
        fetched = now_iso()
        records = []
        cursor_column = str(self.config.settings.get("cursor_column") or "id")
        for row in rows[:limit]:
            ext = str(row.get("external_id") or row.get("id") or row.get(cursor_column))
            observed = row.get("observed_at") or row.get("updated_at")
            records.append(SourceRecordEnvelope(source_type=self.source_type, source_instance=self.config.source_instance, external_id=ext, record_type=str(row.get("record_type") or "row"), observed_at=observed, fetched_at=fetched, source_updated_at=row.get("updated_at"), raw_metadata=row, cursor=str(row.get(cursor_column) or ext), checksum=checksum_payload(row)))
        nxt = records[-1].cursor if records else cursor
        return AdapterPage(records=records, next_cursor=nxt, has_more=len(records) >= limit)
