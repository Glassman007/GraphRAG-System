from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.graph.client import FalkorGraphClient
from scripts.seed_lib import seed_all


def main() -> None:
    client = FalkorGraphClient()
    client.delete_graph()
    result = seed_all(client)
    print(f"Reseed complete: {result['nodes']} node upserts, {result['edges']} edge upserts")


if __name__ == "__main__":
    main()
