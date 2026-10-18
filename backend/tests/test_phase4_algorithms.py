from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from backend.app.services.entity_resolution_service import EntityResolutionService
from backend.app.services.investigation_service import RelationalInvestigationService
from backend.app.services.blast_radius_service import BlastRadiusService
from backend.app.services.knowledge_gap_service import KnowledgeGapService
from backend.app.services.evidence_acquisition_service import EvidenceAcquisitionService
from backend.app.services.decision_genealogy_service import DecisionGenealogyService
from backend.app.services.precedent_service import StructuralPrecedentService
from backend.app.services.planning_service import ConstraintPlanningService
from backend.app.services.simulation_service import CounterfactualSimulationService
from backend.app.services.anomaly_service import GraphAnomalyService
from backend.app.main import app


class _Result:
    def __init__(self, rows):
        self.result_set = rows


class FixtureGraphClient:
    def __init__(self, root: Path):
        self.settings = SimpleNamespace(tenant_id="northstar")
        self.nodes = {}
        self.edges = []
        paths = [root / "fixtures" / "canonical_incident.json", *sorted((root / "fixtures" / "scenarios").glob("*.json"))]
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            for item in data.get("nodes", []):
                node = dict(item["properties"])
                node["id"] = item["id"]
                node["_labels"] = ["Entity", item["label"]]
                self.nodes[item["id"]] = node
            self.edges.extend(data.get("edges", []))

    def read(self, cypher, params=None):
        if "RETURN n ORDER BY n.id" in cypher:
            return _Result([[self.nodes[k]] for k in sorted(self.nodes)])
        if "RETURN a.id, type(r), r, b.id" in cypher:
            rows = []
            for e in sorted(self.edges, key=lambda x: (x["source"], x["type"], x["target"])):
                if e["source"] in self.nodes and e["target"] in self.nodes:
                    rows.append([e["source"], e["type"], dict(e.get("properties") or {}), e["target"]])
            return _Result(rows)
        raise AssertionError(f"Unexpected read query in fixture test: {cypher}")


def _client(project_root: Path):
    return FixtureGraphClient(project_root)


def test_phase4_entity_resolution_preserves_uncertain_candidate(project_root):
    service = EntityResolutionService(_client(project_root))
    accepted = service.resolve_source_record("SRCREC-HR-991")
    assert accepted["status"] == "CONFIRMED"
    assert accepted["canonical_entity"]["id"] == "PERSON-RIYA"
    ambiguous = service.resolve_source_record("SRCREC-CRM-42")
    assert ambiguous["status"] == "UNRESOLVED"
    assert ambiguous["candidates"][0]["entity"]["id"] == "PERSON-RIYA"
    assert ambiguous["candidates"][0]["confidence"] == 0.72
    assert ambiguous["auto_merge_performed"] is False


def test_phase4_relational_investigation_finds_connected_causal_path(project_root):
    result = RelationalInvestigationService(_client(project_root)).investigate_incident("INC-001")
    assert result["candidate_paths"]
    path = result["candidate_paths"][0]
    assert {"MIG-203", "SYS-PRICING-API", "SYS-PRICING-DB"} <= set(path["node_ids"])
    assert any(x["id"] in {"E-003", "E-006"} for x in path["evidence"])
    assert "DEPENDS_ON" in {e["type"] for e in path["edges"]}




def test_phase4_relational_investigation_ignores_operational_about_path_noise(project_root):
    client=_client(project_root)
    # Later phases add Tasks/Investigations that may ABOUT the same incident/change.
    # They must not crowd evidence-backed causal paths out of the bounded search.
    for i in range(200):
        tid=f"TASK-NOISE-{i}"
        client.nodes[tid]={"id":tid,"tenant_id":"northstar","_labels":["Entity","Task"],"status":"OPEN"}
        client.edges.append({"source":tid,"type":"ABOUT","target":"INC-001","properties":{}})
        client.edges.append({"source":tid,"type":"ABOUT","target":"MIG-203","properties":{}})
    result=RelationalInvestigationService(client).investigate_incident("INC-001")
    matching=[p for p in result["candidate_paths"] if {"MIG-203","SYS-PRICING-API","SYS-PRICING-DB"} <= set(p["node_ids"])]
    assert matching
    assert any("SYS-CHECKOUT" in p["node_ids"] for p in matching)

def test_phase4_blast_radius_distinguishes_observed_from_potential(project_root):
    result = BlastRadiusService(_client(project_root)).analyze("SYS-PRICING-DB")
    by_id = {x["system"]["id"]: x for x in result["downstream_dependents"]}
    assert {"SYS-CHECKOUT", "SYS-MOBILE-OFFERS", "SYS-LEGACY-PROMO", "SYS-PRICING-ANALYTICS"} <= set(by_id)
    assert by_id["SYS-CHECKOUT"]["impact"] == "OBSERVED"
    assert by_id["SYS-PRICING-ANALYTICS"]["impact"] == "POTENTIAL"


def test_phase4_knowledge_gaps_keep_q001_q004_explicit(project_root):
    result = KnowledgeGapService(_client(project_root)).detect_for_incident("INC-001")
    qgaps = {g["question"]["id"]: g for g in result["gaps"] if g["kind"] == "QUESTION_GAP"}
    assert {"Q-001", "Q-002", "Q-003", "Q-004"} <= set(qgaps)
    assert "EXPECTED_EVIDENCE_MISSING" in qgaps["Q-001"]["reason_codes"]
    assert "MISSING_OWNER" in qgaps["Q-004"]["reason_codes"]


def test_phase4_tool_routing_is_graph_backed(project_root):
    service = EvidenceAcquisitionService(_client(project_root))
    q1 = service.route_question("Q-001")
    q3 = service.route_question("Q-003")
    assert {r["data_source"]["id"] for r in q1["routes"]} == {"DS-DEPLOY", "DS-GIT"}
    assert {r["data_source"]["id"] for r in q3["routes"]} == {"DS-DEPLOY", "DS-LOG"}
    assert all(r["path"] for r in q1["routes"])


def test_phase4_decision_replay_excludes_future_ledger_events(project_root):
    result = DecisionGenealogyService(_client(project_root)).replay("DEC-INC001-ROLLBACK")
    assert {x["entity"]["id"] for x in result["evidence"]} == {"E-002", "E-003"}
    assert {x["entity"]["id"] for x in result["claims"]} == {"C-002"}
    assert all(x["event"]["occurred_at"] <= "2026-10-16T14:16:00+05:30" for x in result["events"])
    assert result["later_outcomes"][0]["event"]["id"] == "EVT-RECOVERY-OUTCOME"
    assert result["private_chain_of_thought_stored"] is False


def test_phase4_structural_precedent_finds_inc074_without_keyword_dependency(project_root):
    result = StructuralPrecedentService(_client(project_root)).find_precedents("INC-001")
    candidate = next(x for x in result["precedents"] if x["incident"]["id"] == "INC-074")
    assert candidate["structural_similarity"] >= 0.55
    assert candidate["structural_similarity"] > candidate["keyword_component"]
    assert candidate["explanation_paths"]


def test_phase4_constraint_plan_has_topological_action_order(project_root):
    result = ConstraintPlanningService(_client(project_root)).plan_for_incident("INC-001")
    order = [x["action"]["id"] for x in result["steps"]]
    assert order.index("ACT-ROLLBACK-MIG203") < order.index("ACT-VERIFY-ROLLBACK") < order.index("ACT-RESTORE-CHECKOUT")
    assert result["violations"] == []
    assert any(x["action"]["id"] == "ACT-KEEP-ROLLING" for x in result["rejected_candidates"])


def test_phase4_counterfactual_rollback_is_isolated_and_recomputes_graph(project_root):
    result = CounterfactualSimulationService(_client(project_root)).simulate("MIG-203", [{"op": "rollback_change", "change_id": "MIG-203"}])
    assert "SYS-CHECKOUT" in result["canonical_result"]["blast_radius"]["impacted"]
    assert "SYS-CHECKOUT" not in result["counterfactual_result"]["blast_radius"]["impacted"]
    assert result["canonical_mutated"] is False


def test_phase4_anomaly_detection_flags_exact_shadow_dependency(project_root):
    result = GraphAnomalyService(_client(project_root)).detect()
    anomaly = next(x for x in result["anomalies"] if x["rule"] == "FRONTEND_DIRECT_DATABASE")
    assert anomaly["abnormal_edge"]["source"] == "SYS-ANALYTICS-UI"
    assert anomaly["abnormal_edge"]["target"] == "SYS-PROD-ORDERS-DB"
    assert anomaly["normal_paths_present"]


def test_phase4_api_routes_registered_without_raw_cypher_endpoint():
    paths = {route.path for route in app.routes}
    required = {
        "/source-records/{source_record_id}/resolution",
        "/incidents/{incident_id}/investigation",
        "/entities/{entity_id}/blast-radius",
        "/incidents/{incident_id}/knowledge-gaps",
        "/questions/{question_id}/tool-routing",
        "/decisions/{decision_id}/genealogy",
        "/incidents/{incident_id}/precedents",
        "/plans",
        "/simulations",
        "/anomalies",
    }
    assert required <= paths
    assert all("cypher" not in path.lower() for path in paths)
