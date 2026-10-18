from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.graph.client import FalkorGraphClient
from scripts.seed_lib import seed_all


def main() -> None:
    client = FalkorGraphClient()
    result = seed_all(client)
    print(f"Seed complete: {result['nodes']} node upserts, {result['edges']} edge upserts")


if __name__ == "__main__":
    main()
