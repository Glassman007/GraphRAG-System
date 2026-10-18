"""Step 4 regression contracts without live FalkorDB or network side effects."""
from __future__ import annotations
from pathlib import Path
import json

from scripts.verify_step4_demo import offline, data, request

ROOT = Path(__file__).resolve().parents[2]

def test_offline_acceptance_matrix_and_graph_contracts():
    result=offline()
    assert result["ok"], result["errors"]
    assert result["scenario_count"] == 24
    assert set(result["tracks"]) == {"COMPANY_BRAIN", "CONNECTED_AGENTS", "AGENT_MEMORY_COORDINATION"}

def test_demo_ui_routes_keep_original_work_and_knowledge_paths():
    app=(ROOT / "frontend/src/App.tsx").read_text(encoding="utf-8")
    shell=(ROOT / "frontend/src/components/AppShell.tsx").read_text(encoding="utf-8")
    for path in ["/demo", "/situations", "/investigations", "/work", "/knowledge", "/company-brain", "/decisions", "/simulations"]:
        assert f'path="{path}"' in app
    assert "['Demo Lab','/demo']" in shell

def test_demo_does_not_load_private_evaluator_answer_file():
    files=[ROOT/"frontend/src/data/asteriaScenarios.json",ROOT/"frontend/src/demo/demoModel.ts",ROOT/"frontend/src/pages/DemoPage.tsx",ROOT/"frontend/src/demo/LiveTracePanel.tsx"]
    for path in files:
        source=path.read_text(encoding="utf-8")
        assert "evaluation_only.json" not in source
        assert "ground_truth/" not in source

def test_all_scenarios_have_safe_entry_points():
    for item in data():
        assert item['entry_ids']
        assert item['permitted_operations']
        assert item['scenario_id'].startswith('AST-')
        assert item['starting_state']['fixture_version']=='asteria-v1'
