"""VERINEX Company Brain registry (backend stage 1).

Persistent *metadata* only. No graph data is copied or modified. Registrations are
operator-managed in this stage; APIs expose tenant-scoped read-only discovery.
Graph selection for agent runs / ingestion belongs to subsequent stages.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient

_GRAPH_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,95}$")
_TENANT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REJECTED_PREFIXES = (
    "phase", "accept_", "verinex_neon_", "verinex_stage", "company_brain_test_",
)


class InvalidGraphRegistration(ValueError):
    """The graph or tenant is not eligible for registration."""


class GraphNotRegistered(LookupError):
    """The requested graph isn't registered for this authenticated tenant."""


def _validate(graph_id: str, tenant_id: str) -> None:
    if not _GRAPH_ID.fullmatch(graph_id):
        raise InvalidGraphRegistration("Graph ID must be 1-96 letters, digits or underscores, beginning with a letter")
    if not _TENANT_ID.fullmatch(tenant_id):
        raise InvalidGraphRegistration("Invalid tenant ID")
    lowered = graph_id.lower()
    # Acceptance, transient test and derived memory graphs are never selectable
    # as standalone Company Brains via this operator registration path.
    if lowered.startswith(_REJECTED_PREFIXES) or lowered.endswith("_agent_memory") or "_neon_" in lowered:
        raise InvalidGraphRegistration("Test, stage and agent-memory graphs cannot be registered as Company Brains")


class GraphRegistry:
    """SQLite catalogue with explicit (tenant, graph) bindings.

    Never return FalkorDB.list_graphs() directly to API users. Registration
    requires a trusted local operator, an EXISTING graph, and matching tenant
    data. A registration alone does not authorize arbitrary Cypher access.
    """

    def __init__(self, path: str | Path | None = None):
        root = Path(__file__).resolve().parents[3]
        configured = path or os.getenv("VERINEX_GRAPH_REGISTRY_PATH")
        self.path = Path(configured) if configured else root / ".verinex" / "graph_registry.sqlite3"

    def _db(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("""CREATE TABLE IF NOT EXISTS company_brains (
            tenant_id TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            registered_at TEXT NOT NULL,
            PRIMARY KEY (tenant_id, graph_id)
        )""")
        return db

    @staticmethod
    def _available_names(client: FalkorGraphClient) -> set[str]:
        return set(client.db.list_graphs())

    def register_existing(self, *, graph_id: str, tenant_id: str, display_name: str,
                          client: FalkorGraphClient | None = None) -> dict[str, Any]:
        _validate(graph_id, tenant_id)
        display_name = display_name.strip()
        if not 1 <= len(display_name) <= 100:
            raise InvalidGraphRegistration("Display name must contain 1-100 characters")
        client = client or FalkorGraphClient()
        if graph_id not in self._available_names(client):
            raise InvalidGraphRegistration("Graph does not exist; registration does not create graphs")
        # Guard against accidentally assigning a graph to an unrelated tenant.
        # Does not establish exclusive ownership: company_brain may be shared.
        try:
            rows = client.db.select_graph(graph_id).ro_query(
                "MATCH (n {tenant_id:$tenant}) RETURN n.id LIMIT 1",
                {"tenant": tenant_id},
            ).result_set
        except Exception as exc:
            raise InvalidGraphRegistration("Could not verify tenant membership in selected graph") from exc
        if not rows:
            raise InvalidGraphRegistration("Selected graph has no records belonging to the specified tenant")
        at = datetime.now(timezone.utc).isoformat()
        with self._db() as db:
            db.execute("""INSERT INTO company_brains (tenant_id, graph_id, display_name, registered_at)
                VALUES (?, ?, ?, ?) ON CONFLICT (tenant_id,graph_id)
                DO UPDATE SET display_name=excluded.display_name""",
                (tenant_id, graph_id, display_name, at))
        return self.resolve(tenant_id=tenant_id, graph_id=graph_id)

    def create_dedicated(self, *, tenant_id: str, display_name: str,
                         client: FalkorGraphClient | None = None) -> dict[str, Any]:
        """Provision a *new* tenant Company Brain, never redirect or copy an existing one.

        A technical anchor (not an Entity) makes an otherwise empty graph exist
        in FalkorDB. No external source is ingested by provisioning.
        """
        name = display_name.strip()
        if not 1 <= len(name) <= 100:
            raise InvalidGraphRegistration('Display name must contain 1-100 characters')
        if not _TENANT_ID.fullmatch(tenant_id):
            raise InvalidGraphRegistration('Invalid tenant ID')
        client = client or FalkorGraphClient()
        available = self._available_names(client)
        graph_id = ''
        for _ in range(5):
            proposed = 'source_' + uuid.uuid4().hex[:20]
            if proposed not in available:
                graph_id = proposed
                break
        if not graph_id:
            raise InvalidGraphRegistration('Could not allocate a unique graph ID')
        _validate(graph_id, tenant_id)
        graph = client.db.select_graph(graph_id)
        try:
            graph.query('CREATE (:VERINEXGraphAnchor {tenant_id:$tenant_id, graph_id:$graph_id, dedicated:true})',
                        {'tenant_id': tenant_id, 'graph_id': graph_id})
            registered = self.register_existing(graph_id=graph_id, tenant_id=tenant_id,
                                                display_name=name, client=client)
        except Exception:
            # Only ever delete the newly allocated graph, never an existing graph.
            try:
                graph.delete()
            except Exception:
                pass
            raise
        return {**registered, 'dedicated': True}

    def resolve(self, *, tenant_id: str, graph_id: str) -> dict[str, Any]:
        # Normalize untrusted IDs before any potential graph interaction.
        _validate(graph_id, tenant_id)
        with self._db() as db:
            row = db.execute("""SELECT tenant_id, graph_id, display_name, registered_at
                FROM company_brains WHERE tenant_id=? AND graph_id=?""",
                (tenant_id, graph_id)).fetchone()
        if row is None:
            raise GraphNotRegistered("Company Brain not found for this tenant")
        return dict(row)

    def list_for_tenant(self, *, tenant_id: str, client: FalkorGraphClient | None = None) -> dict[str, Any]:
        if not _TENANT_ID.fullmatch(tenant_id):
            raise InvalidGraphRegistration("Invalid tenant ID")
        with self._db() as db:
            rows = [dict(row) for row in db.execute(
                "SELECT graph_id, display_name, registered_at FROM company_brains WHERE tenant_id=? ORDER BY display_name,graph_id",
                (tenant_id,)).fetchall()]
        # Never expose other tenants' graph IDs or discovered unregistered DB names.
        available = self._available_names(client or FalkorGraphClient()) if rows else set()
        items = [{**row, "available": row["graph_id"] in available} for row in rows]
        default_name = Settings.from_env().falkordb_graph
        return {"items": items, "default_graph_id": default_name if any(
            x["graph_id"] == default_name and x["available"] for x in items) else None}

    def client_for_graph(self, *, tenant_id: str, graph_id: str,
                         settings: Settings | None = None,
                         catalog_client: FalkorGraphClient | None = None) -> FalkorGraphClient:
        """Future workspace/ingestion entrypoint. Never mutate server-wide settings."""
        self.resolve(tenant_id=tenant_id, graph_id=graph_id)
        if graph_id not in self._available_names(catalog_client or FalkorGraphClient()):
            raise GraphNotRegistered("Registered Company Brain is currently unavailable")
        scoped = (settings or Settings.from_env()).model_copy(update={
            "tenant_id": tenant_id, "falkordb_graph": graph_id,
        })
        return FalkorGraphClient(scoped)


def main() -> int:
    parser = argparse.ArgumentParser(description="Register existing Company Brains; trusted local operator only")
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("register", help="Register an existing graph for one tenant")
    add.add_argument("--graph", required=True)
    add.add_argument("--tenant", required=True)
    add.add_argument("--name", required=True)
    show = sub.add_parser("list", help="List registered graphs for one tenant")
    show.add_argument("--tenant", required=True)
    args = parser.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    registry = GraphRegistry()
    try:
        if args.command == "register":
            record = registry.register_existing(
                graph_id=args.graph, tenant_id=args.tenant, display_name=args.name)
            print(json.dumps({"registered": record}, indent=2))
        else:
            print(json.dumps(registry.list_for_tenant(tenant_id=args.tenant), indent=2))
    except (InvalidGraphRegistration, GraphNotRegistered) as exc:
        parser.exit(2, f"Registration error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
