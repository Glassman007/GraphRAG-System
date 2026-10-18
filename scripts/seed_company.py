from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.schema import apply_schema
from scripts.seed_lib import load_fixture, seed_fixture

ORGANIZATION_LABELS = {"Person", "Team", "System", "DataSource", "Tool"}
ORGANIZATION_RELS = {"MEMBER_OF", "OWNS", "RESPONSIBLE_FOR", "EXPERT_IN", "DEPENDS_ON"}


def main() -> None:
    client = FalkorGraphClient()
    apply_schema(client)
    fixture = load_fixture(ROOT / "fixtures" / "canonical_incident.json")
    result = seed_fixture(client, fixture, labels=ORGANIZATION_LABELS, rels=ORGANIZATION_RELS)
    print(f"Seeded organization: {result['nodes']} nodes, {result['edges']} edges into {client.settings.falkordb_graph}")


if __name__ == "__main__":
    main()
