from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.graph.schema import NODE_LABELS, RELATIONSHIP_TYPES
from scripts.seed_lib import load_fixture, scenario_paths


def validate(path: Path) -> None:
    data = load_fixture(path)
    assert data.get("scenario_id")
    assert data.get("ground_truth"), f"{path.name}: missing ground_truth"
    ids = [n["id"] for n in data.get("nodes", [])]
    assert len(ids) == len(set(ids)), f"{path.name}: duplicate node IDs"
    idset = set(ids)
    for n in data.get("nodes", []):
        assert n["label"] in NODE_LABELS, f"{path.name}: unknown label {n['label']}"
        assert n["properties"].get("tenant_id"), f"{path.name}: node lacks tenant_id"
    for e in data.get("edges", []):
        assert e["type"] in RELATIONSHIP_TYPES, f"{path.name}: unknown rel {e['type']}"
        # Support fixtures may reference canonical organization nodes.
        if e["source"] not in idset or e["target"] not in idset:
            assert path.name != "canonical_incident.json" or False, f"canonical edge endpoint missing: {e}"


def main() -> None:
    for path in scenario_paths():
        validate(path)
        print(f"OK {path.name}")


if __name__ == "__main__":
    main()
