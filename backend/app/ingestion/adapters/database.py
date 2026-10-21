from __future__ import annotations

import os
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

    def _dsn(self) -> str:
        dsn = credential_values(self.config).get("dsn") or os.getenv(str(self.config.settings.get("dsn_env") or "INGESTION_DATABASE_DSN"))
        if not dsn:
            raise ValueError("Database source has no configured connection credential")
        return str(dsn)

    def _connect(self):
        try:
            import psycopg  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Live PostgreSQL ingestion requires psycopg") from exc
        return psycopg.connect(self._dsn(), connect_timeout=10,
                               options="-c default_transaction_read_only=on")

    def health_check(self) -> dict[str, Any]:
        if self.config.fixture_path:
            return super().health_check()
        if self.row_provider:
            return {"ok": True, "source_id": self.config.id, "live": True, "read_only": True}
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute("SELECT current_database(), current_setting('transaction_read_only')")
                database, read_only = cur.fetchone()
                if read_only != "on":
                    raise RuntimeError("Database connection is not read-only")
                cur.execute("SELECT 1 FROM pg_catalog.pg_class LIMIT 1")
            return {"ok": True, "source_id": self.config.id, "live": True,
                    "read_only": True, "database": database,
                    "checks": {"authentication": "PASS", "reachability": "PASS", "required_permission": "PASS", "api_access": "PASS"}}
        except (ValueError, RuntimeError):
            raise
        except Exception:
            return {"ok": False, "status": "UNREACHABLE", "live": True,
                    "message": "PostgreSQL connection or catalog read failed"}

    def _fetch_schema(self, *, cursor: str | None) -> AdapterPage:
        schemas = self.config.settings.get("schemas") or ["public"]
        if not isinstance(schemas, list) or not schemas or not all(isinstance(s, str) and s for s in schemas):
            raise ValueError("Database schema scope must be a nonempty list of schema names")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cur.execute("SELECT current_database(), current_setting('transaction_read_only')")
            database, read_only = cur.fetchone()
            if read_only != "on":
                raise RuntimeError("Database schema discovery requires a read-only connection")
            cur.execute("""SELECT c.oid, n.nspname, c.relname
                           FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
                           WHERE c.relkind IN ('r','p') AND n.nspname = ANY(%s)
                           ORDER BY n.nspname,c.relname""", (schemas,))
            tables = [{"oid": oid, "schema": schema, "name": name, "columns": [], "constraints": []}
                      for oid, schema, name in cur.fetchall()]
            by_oid = {t["oid"]: t for t in tables}
            if by_oid:
                cur.execute("""SELECT a.attrelid,a.attnum,a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),a.attnotnull
                               FROM pg_catalog.pg_attribute a WHERE a.attrelid = ANY(%s)
                               AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attrelid,a.attnum""", (list(by_oid),))
                attrs: dict[int, dict[int, str]] = {}
                for oid, num, name, data_type, not_null in cur.fetchall():
                    by_oid[oid]["columns"].append({"name": name, "data_type": data_type, "not_null": not_null})
                    attrs.setdefault(oid, {})[num] = name
                cur.execute("""SELECT con.conrelid,con.conname,con.contype,con.conkey,con.confrelid,con.confkey,
                                      pg_catalog.pg_get_constraintdef(con.oid)
                               FROM pg_catalog.pg_constraint con WHERE con.conrelid = ANY(%s)
                               AND con.contype IN ('p','f') ORDER BY con.conrelid,con.conname""", (list(by_oid),))
                for oid, name, kind, keys, target_oid, target_keys, definition in cur.fetchall():
                    if kind == "f" and target_oid not in by_oid:
                        raise ValueError("A foreign key references a table outside the registered schema scope")
                    by_oid[oid]["constraints"].append({
                        "name": name, "kind": "PRIMARY_KEY" if kind == "p" else "FOREIGN_KEY",
                        "columns": [attrs[oid][num] for num in keys],
                        "referenced_table": (f"{by_oid[target_oid]['schema']}.{by_oid[target_oid]['name']}" if kind == "f" else None),
                        "referenced_columns": ([attrs[target_oid][num] for num in target_keys] if kind == "f" else []),
                        "definition": definition,
                    })
            for table in tables:
                table.pop("oid")
        raw = {"database": database, "schemas": sorted(schemas), "tables": tables}
        checksum = checksum_payload(raw)
        fetched = now_iso()
        record = SourceRecordEnvelope(source_type=self.source_type, source_instance=self.config.source_instance,
                                      external_id=f"{database}:schema", record_type="database_schema",
                                      fetched_at=fetched, version=checksum, raw_metadata=raw,
                                      canonical_source_uri=f"postgresql://{database}", cursor=checksum,
                                      checksum=checksum)
        return AdapterPage(records=[record], next_cursor=checksum, has_more=False)

    def fetch(self, *, cursor: str | None = None, limit: int = 100) -> AdapterPage:
        if self.config.fixture_path:
            return super().fetch(cursor=cursor, limit=limit)
        if self.config.settings.get("mode") == "schema":
            return self._fetch_schema(cursor=cursor)
        rows: list[dict[str, Any]]
        if self.row_provider:
            rows = self.row_provider(cursor, limit)
        else:
            try:
                import psycopg  # type: ignore
            except ImportError as exc:
                raise RuntimeError("Live PostgreSQL ingestion requires optional psycopg") from exc
            query = self.config.settings.get("query")
            cursor_column = self.config.settings.get("cursor_column")
            if not query or not cursor_column:
                raise RuntimeError("Database source requires configured DSN env, fixed query and cursor_column")
            # Query text comes only from server-side SourceConfig. Public APIs cannot supply SQL.
            with self._connect() as conn:
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
