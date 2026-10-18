from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.schema import apply_schema


def main() -> None:
    client = FalkorGraphClient()
    apply_schema(client)
    print(f"Schema applied to graph={client.settings.falkordb_graph} tenant={client.settings.tenant_id}")


if __name__ == "__main__":
    main()
