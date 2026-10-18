from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.schema import apply_schema
from scripts.seed_lib import load_fixture, seed_fixture, scenario_paths


def main() -> None:
    client = FalkorGraphClient()
    apply_schema(client)
    total_nodes = total_edges = 0
    for path in scenario_paths():
        result = seed_fixture(client, load_fixture(path))
        total_nodes += result["nodes"]
        total_edges += result["edges"]
        print(f"Seeded {path.name}: {result['nodes']} nodes, {result['edges']} edges")
    print(f"Total fixture writes: {total_nodes} node upserts, {total_edges} edge upserts")


if __name__ == "__main__":
    main()
