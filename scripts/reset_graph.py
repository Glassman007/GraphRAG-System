from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.graph.client import FalkorGraphClient


def main() -> None:
    client = FalkorGraphClient()
    deleted = client.delete_graph()
    print(f"Graph {client.settings.falkordb_graph!r} {'deleted' if deleted else 'was already absent'}.")


if __name__ == "__main__":
    main()
