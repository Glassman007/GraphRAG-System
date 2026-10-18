from __future__ import annotations

import json
from pathlib import Path


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_canonical_incident_fixture_integrity(project_root: Path):
    fixture = _load(project_root / "fixtures" / "canonical_incident.json")
    ids = {n["id"] for n in fixture["nodes"]}
    rels = {(e["source"], e["type"], e["target"]) for e in fixture["edges"]}

    required_ids = {
        "INC-001", "DPL-882", "MIG-203", "POL-DB-04", "COM-017",
        "C-001", "C-002", "E-001", "E-008", "Q-001", "Q-004",
        "SYS-CHECKOUT", "SYS-PRICING-API", "SYS-PRICING-DB", "SYS-LEGACY-PROMO",
    }
    assert required_ids <= ids
    assert ("C-001", "CONTRADICTS", "C-002") in rels
    assert ("SYS-CHECKOUT", "DEPENDS_ON", "SYS-PRICING-API") in rels
    assert ("SYS-PRICING-API", "DEPENDS_ON", "SYS-PRICING-DB") in rels
    assert fixture["ground_truth"]["primary_root_cause"].startswith("Backward-incompatible")


def test_supporting_scenario_fixture_integrity(project_root: Path):
    paths = sorted((project_root / "fixtures" / "scenarios").glob("*.json"))
    assert len(paths) >= 6
    for path in paths:
        data = _load(path)
        assert data["scenario_id"]
        assert data["nodes"]
        assert data["ground_truth"]
        node_ids = [n["id"] for n in data["nodes"]]
        assert len(node_ids) == len(set(node_ids)), path.name
