from __future__ import annotations

from typing import Any
from backend.app.config import Settings


class FalkorGraphClient:
    """Small, explicit wrapper around the official FalkorDB Python client."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings.from_env()
        kwargs: dict[str, Any] = {
            "host": self.settings.falkordb_host,
            "port": self.settings.falkordb_port,
            "socket_connect_timeout": 2,
            "socket_timeout": 5,
        }
        if self.settings.falkordb_password:
            kwargs["password"] = self.settings.falkordb_password
        try:
            from falkordb import FalkorDB
        except ImportError as exc:
            raise RuntimeError("FalkorDB Python client is not installed. Run: pip install -r requirements.txt") from exc
        self.db = FalkorDB(**kwargs)
        self.graph = self.db.select_graph(self.settings.falkordb_graph)

    def query(self, cypher: str, params: dict[str, Any] | None = None):
        return self.graph.query(cypher, params or {})

    def read(self, cypher: str, params: dict[str, Any] | None = None):
        return self.graph.ro_query(cypher, params or {})

    def health_check(self) -> dict[str, Any]:
        result = self.query("RETURN 1 AS ok")
        ok = bool(result.result_set and result.result_set[0][0] == 1)
        return {
            "ok": ok,
            "host": self.settings.falkordb_host,
            "port": self.settings.falkordb_port,
            "graph": self.settings.falkordb_graph,
        }

    def delete_graph(self) -> bool:
        try:
            self.graph.delete()
            self.graph = self.db.select_graph(self.settings.falkordb_graph)
            return True
        except Exception as exc:  # graph-missing errors differ between server versions
            text = str(exc).lower()
            if "does not exist" in text or "unknown graph" in text or "not found" in text or "empty key" in text:
                self.graph = self.db.select_graph(self.settings.falkordb_graph)
                return False
            raise
