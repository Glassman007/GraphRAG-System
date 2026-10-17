from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.graph.schema import apply_schema
from backend.app.graph.temporal import with_temporal_epochs

ROOT = Path(__file__).resolve().parents[1]


def load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def seed_fixture(client: FalkorGraphClient, fixture: dict, *, labels: set[str] | None = None, rels: set[str] | None = None) -> dict[str, int]:
    node_ids = set()
    node_count = 0
    edge_count = 0
    for item in fixture.get("nodes", []):
        if labels is not None and item["label"] not in labels:
            continue
        upsert_node(client, item["label"], item["id"], with_temporal_epochs(item.get("properties", {})))
        node_ids.add(item["id"])
        node_count += 1

    for item in fixture.get("edges", []):
        if rels is not None and item["type"] not in rels:
            continue
        # For filtered organization seeding, only create edges whose endpoints were seeded.
        if labels is not None and (item["source"] not in node_ids or item["target"] not in node_ids):
            continue
        upsert_relationship(
            client, item["source"], item["type"], item["target"],
            with_temporal_epochs(item.get("properties", {})),
        )
        edge_count += 1
    return {"nodes": node_count, "edges": edge_count}


def scenario_paths() -> Iterable[Path]:
    yield ROOT / "fixtures" / "canonical_incident.json"
    yield from sorted((ROOT / "fixtures" / "scenarios").glob("*.json"))


def seed_all(client: FalkorGraphClient) -> dict[str, int]:
    apply_schema(client)
    totals = {"nodes": 0, "edges": 0}
    for path in scenario_paths():
        result = seed_fixture(client, load_fixture(path))
        totals["nodes"] += result["nodes"]
        totals["edges"] += result["edges"]
    return totals
