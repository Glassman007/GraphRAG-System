from __future__ import annotations

import pytest

from backend.app.graph.mutations import delete_relationship, upsert_node, upsert_relationship
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
from backend.app.services.phase4_graph import GraphSnapshot

pytestmark = pytest.mark.integration


def test_phase4_entity_resolution_scn_identity(integration_client):
    service = EntityResolutionService(integration_client)
    accepted = service.resolve_source_record("SRCREC-HR-991")
    unresolved = service.resolve_source_record("SRCREC-CRM-42")
    assert accepted["canonical_entity"]["id"] == "PERSON-RIYA"
    assert accepted["status"] == "CONFIRMED"
    assert unresolved["status"] == "UNRESOLVED"
    riya = next(x for x in unresolved["candidates"] if x["entity"]["id"] == "PERSON-RIYA")
    assert riya["confidence"] == 0.72
    assert unresolved["auto_merge_performed"] is False


def test_phase4_relational_investigation_inc001(integration_client):
    result = RelationalInvestigationService(integration_client).investigate_incident("INC-001")
    assert result["candidate_paths"]
    matching = [p for p in result["candidate_paths"] if {"MIG-203", "SYS-PRICING-API", "SYS-PRICING-DB"} <= set(p["node_ids"])]
    assert matching
    assert any("SYS-CHECKOUT" in p["node_ids"] for p in matching)
    assert any(p["evidence"] for p in matching)


def test_phase4_blast_radius_pricing_db(integration_client):
    result = BlastRadiusService(integration_client).analyze("SYS-PRICING-DB", max_depth=6)
    by_id = {x["system"]["id"]: x for x in result["downstream_dependents"]}
    assert {"SYS-CHECKOUT", "SYS-MOBILE-OFFERS", "SYS-LEGACY-PROMO", "SYS-PRICING-ANALYTICS"} <= set(by_id)
    assert by_id["SYS-CHECKOUT"]["impact"] == "OBSERVED"
    assert by_id["SYS-MOBILE-OFFERS"]["impact"] == "POTENTIAL"


def test_phase4_knowledge_gaps_q001_q004(integration_client):
    result = KnowledgeGapService(integration_client).detect_for_incident("INC-001")
    qgaps = {g["question"]["id"]: g for g in result["gaps"] if g["kind"] == "QUESTION_GAP"}
    assert {"Q-001", "Q-002", "Q-003", "Q-004"} <= set(qgaps)
    assert "EXPECTED_EVIDENCE_MISSING" in qgaps["Q-001"]["reason_codes"]
    assert "MISSING_OWNER" in qgaps["Q-004"]["reason_codes"]
    assert qgaps["Q-001"]["blocking_entities"]


def test_phase4_tool_routing_and_mock_acquisition_writes_provenance(integration_client):
    service = EvidenceAcquisitionService(integration_client)
    q1 = service.route_question("Q-001")
    q3 = service.route_question("Q-003")
    assert {x["data_source"]["id"] for x in q1["routes"]} == {"DS-DEPLOY", "DS-GIT"}
    assert {x["data_source"]["id"] for x in q3["routes"]} == {"DS-DEPLOY", "DS-LOG"}

    upsert_node(integration_client, "Question", "Q-P4-ACQ", {
        "text": "Retrieve a deterministic log fact", "status": "OPEN", "priority": "LOW", "created_at": "2026-10-16T15:00:00+05:30"
    })
    upsert_relationship(integration_client, "Q-P4-ACQ", "ABOUT", "SYS-PRICING-API", {"valid_from": "2026-10-16T15:00:00+05:30", "confidence": 1.0})
    upsert_relationship(integration_client, "Q-P4-ACQ", "REQUIRES", "TOOL-LOG-LOOKUP", {"valid_from": "2026-10-16T15:00:00+05:30", "confidence": 1.0, "required": True})
    acquired = service.acquire_mock(
        "Q-P4-ACQ", evidence_id="E-P4-ACQ", evidence_name="Mocked log fact", evidence_type="log",
        observed_at="2026-10-16T15:01:00+05:30", confidence=0.95,
    )
    assert acquired["tool_request"]["tool_id"] == "TOOL-LOG-LOOKUP"
    snapshot = GraphSnapshot.load(integration_client)
    assert snapshot.node("E-P4-ACQ")["source_ref_id"] == "DS-LOG"
    assert any(e.target == "DS-LOG" for e in snapshot.edges_from("E-P4-ACQ", {"DERIVED_FROM"}))
    assert any(e.target == "E-P4-ACQ" for e in snapshot.edges_from("Q-P4-ACQ", {"RESOLVED_BY"}))


def test_phase4_decision_genealogy_replay_is_time_aware(integration_client):
    result = DecisionGenealogyService(integration_client).replay("DEC-INC001-ROLLBACK")
    assert {x["entity"]["id"] for x in result["claims"]} == {"C-002"}
    assert {x["entity"]["id"] for x in result["evidence"]} == {"E-002", "E-003"}
    assert {x["entity"]["id"] for x in result["policies"]} == {"POL-DB-04"}
    assert all(x["event"]["occurred_at"] <= "2026-10-16T14:16:00+05:30" for x in result["events"])
    assert result["later_outcomes"][0]["event"]["id"] == "EVT-RECOVERY-OUTCOME"


def test_phase4_structural_precedent_inc074(integration_client):
    result = StructuralPrecedentService(integration_client).find_precedents("INC-001")
    match = next(x for x in result["precedents"] if x["incident"]["id"] == "INC-074")
    assert match["structural_similarity"] >= 0.55
    assert match["structural_similarity"] > match["keyword_component"]
    assert match["explanation_paths"]


def test_phase4_constraint_plan_is_graph_backed_partial_order(integration_client):
    result = ConstraintPlanningService(integration_client).plan_for_incident("INC-001")
    ids = [x["action"]["id"] for x in result["steps"]]
    assert ids.index("ACT-ROLLBACK-MIG203") < ids.index("ACT-VERIFY-ROLLBACK") < ids.index("ACT-RESTORE-CHECKOUT")
    assert result["violations"] == []
    assert any("ACT-VERIFY-ROLLBACK-[:REQUIRES]->ACT-ROLLBACK-MIG203" == x for x in result["constraint_paths"])
    assert any(x["action"]["id"] == "ACT-KEEP-ROLLING" for x in result["rejected_candidates"])


def test_phase4_counterfactual_simulation_does_not_mutate_canonical(integration_client):
    before = GraphSnapshot.load(integration_client)
    assert any(e.source == "MIG-203" and e.type == "CHANGED" and e.target == "SYS-PRICING-DB" for e in before.edges)
    result = CounterfactualSimulationService(integration_client).simulate("MIG-203", [{"op": "rollback_change", "change_id": "MIG-203"}])
    assert "SYS-CHECKOUT" in result["canonical_result"]["blast_radius"]["impacted"]
    assert "SYS-CHECKOUT" not in result["counterfactual_result"]["blast_radius"]["impacted"]
    after = GraphSnapshot.load(integration_client)
    assert any(e.source == "MIG-203" and e.type == "CHANGED" and e.target == "SYS-PRICING-DB" for e in after.edges)
    assert after.node("MIG-203")["status"] == "DEPLOYED"


def test_phase4_anomaly_scn_anom(integration_client):
    result = GraphAnomalyService(integration_client).detect()
    anomaly = next(x for x in result["anomalies"] if x["rule"] == "FRONTEND_DIRECT_DATABASE")
    assert anomaly["abnormal_edge"]["source"] == "SYS-ANALYTICS-UI"
    assert anomaly["abnormal_edge"]["target"] == "SYS-PROD-ORDERS-DB"
    assert anomaly["normal_paths_present"]


def test_phase4_graph_necessity_entity_resolution_candidate_edge(integration_client):
    service = EntityResolutionService(integration_client)
    before = service.resolve_source_record("SRCREC-CRM-42")
    props = {"valid_from": "2026-10-15T00:00:00+05:30", "confidence": 0.72, "status": "UNRESOLVED"}
    try:
        assert delete_relationship(integration_client, "SRCREC-CRM-42", "CANDIDATE_MATCH", "PERSON-RIYA") >= 1
        after = service.resolve_source_record("SRCREC-CRM-42")
        riya_before = next(x for x in before["candidates"] if x["entity"]["id"] == "PERSON-RIYA")
        riya_after = next(x for x in after["candidates"] if x["entity"]["id"] == "PERSON-RIYA")
        assert riya_after["confidence"] < riya_before["confidence"]
        assert not any("CANDIDATE_MATCH" in p for p in riya_after["graph_paths"])
    finally:
        upsert_relationship(integration_client, "SRCREC-CRM-42", "CANDIDATE_MATCH", "PERSON-RIYA", props)


def test_phase4_graph_necessity_investigation_change_edges(integration_client):
    service = RelationalInvestigationService(integration_client)
    assert service.investigate_incident("INC-001")["candidate_paths"]
    changed = {"valid_from": "2026-10-16T14:03:00+05:30", "confidence": 1.0, "source_ref_id": "DS-GIT"}
    affects = {"valid_from": "2026-10-16T14:03:00+05:30", "confidence": 0.9}
    try:
        delete_relationship(integration_client, "MIG-203", "CHANGED", "SYS-PRICING-DB")
        delete_relationship(integration_client, "MIG-203", "AFFECTS", "SYS-PRICING-API")
        assert RelationalInvestigationService(integration_client).investigate_incident("INC-001")["candidate_paths"] == []
    finally:
        upsert_relationship(integration_client, "MIG-203", "CHANGED", "SYS-PRICING-DB", changed)
        upsert_relationship(integration_client, "MIG-203", "AFFECTS", "SYS-PRICING-API", affects)


def test_phase4_graph_necessity_blast_radius_dependency_edge(integration_client):
    service = BlastRadiusService(integration_client)
    before = {x["system"]["id"] for x in service.analyze("SYS-PRICING-DB")["downstream_dependents"]}
    props = {"valid_from": "2024-02-01T00:00:00+05:30", "confidence": 1.0, "source_ref_id": "DS-DEPLOY"}
    try:
        delete_relationship(integration_client, "SYS-PRICING-API", "DEPENDS_ON", "SYS-PRICING-DB")
        after = {x["system"]["id"] for x in service.analyze("SYS-PRICING-DB")["downstream_dependents"]}
        assert "SYS-CHECKOUT" in before and "SYS-CHECKOUT" not in after
        assert "SYS-PRICING-ANALYTICS" in after
    finally:
        upsert_relationship(integration_client, "SYS-PRICING-API", "DEPENDS_ON", "SYS-PRICING-DB", props)


def test_phase4_graph_necessity_tool_route_edges(integration_client):
    service = EvidenceAcquisitionService(integration_client)
    assert service.route_question("Q-001")["routes"]
    p1 = {"valid_from": "2026-10-16T14:12:00+05:30", "confidence": 1.0, "required": True}
    try:
        delete_relationship(integration_client, "Q-001", "REQUIRES", "TOOL-DEPLOY-LOOKUP")
        delete_relationship(integration_client, "Q-001", "REQUIRES", "TOOL-GIT-LOOKUP")
        assert service.route_question("Q-001")["status"] == "NO_GRAPH_ROUTE"
    finally:
        upsert_relationship(integration_client, "Q-001", "REQUIRES", "TOOL-DEPLOY-LOOKUP", p1)
        upsert_relationship(integration_client, "Q-001", "REQUIRES", "TOOL-GIT-LOOKUP", p1)


def test_phase4_graph_necessity_replay_based_on_edges(integration_client):
    service = DecisionGenealogyService(integration_client)
    assert service.replay("DEC-INC001-ROLLBACK")["complete"] is True
    targets = ["C-002", "E-002", "E-003", "POL-DB-04"]
    props = {"valid_from": "2026-10-16T14:16:00+05:30", "confidence": 1.0}
    try:
        for target in targets:
            delete_relationship(integration_client, "DEC-INC001-ROLLBACK", "BASED_ON", target)
        degraded = service.replay("DEC-INC001-ROLLBACK")
        assert degraded["complete"] is False
        assert degraded["claims"] == [] and degraded["evidence"] == [] and degraded["policies"] == []
    finally:
        for target in targets:
            upsert_relationship(integration_client, "DEC-INC001-ROLLBACK", "BASED_ON", target, props)


def test_phase4_graph_necessity_precedent_topology(integration_client):
    service = StructuralPrecedentService(integration_client)
    before = next(x for x in service.find_precedents("INC-001")["precedents"] if x["incident"]["id"] == "INC-074")
    changed = {"valid_from": "2026-06-11T09:58:00+05:30", "confidence": 1.0}
    try:
        delete_relationship(integration_client, "MIG-074", "CHANGED", "SYS-INVENTORY")
        delete_relationship(integration_client, "MIG-074", "AFFECTS", "SYS-INVENTORY-WORKER")
        degraded = StructuralPrecedentService(integration_client).find_precedents("INC-001")
        match = next((x for x in degraded["precedents"] if x["incident"]["id"] == "INC-074"), None)
        assert match is None or match["structural_similarity"] < before["structural_similarity"]
    finally:
        upsert_relationship(integration_client, "MIG-074", "CHANGED", "SYS-INVENTORY", changed)
        upsert_relationship(integration_client, "MIG-074", "AFFECTS", "SYS-INVENTORY-WORKER", changed)


def test_phase4_graph_necessity_planning_constraints(integration_client):
    before = ConstraintPlanningService(integration_client).plan_for_incident("INC-001")
    assert any("REQUIRES" in p for p in before["constraint_paths"])
    req1 = {"valid_from": "2026-10-16T14:16:00+05:30", "confidence": 1.0, "required": True}
    try:
        delete_relationship(integration_client, "ACT-VERIFY-ROLLBACK", "REQUIRES", "ACT-ROLLBACK-MIG203")
        delete_relationship(integration_client, "ACT-RESTORE-CHECKOUT", "REQUIRES", "ACT-VERIFY-ROLLBACK")
        degraded = ConstraintPlanningService(integration_client).plan_for_incident("INC-001")
        assert "ACT-VERIFY-ROLLBACK-[:REQUIRES]->ACT-ROLLBACK-MIG203" not in degraded["constraint_paths"]
        assert "ACT-RESTORE-CHECKOUT-[:REQUIRES]->ACT-VERIFY-ROLLBACK" not in degraded["constraint_paths"]
    finally:
        upsert_relationship(integration_client, "ACT-VERIFY-ROLLBACK", "REQUIRES", "ACT-ROLLBACK-MIG203", req1)
        upsert_relationship(integration_client, "ACT-RESTORE-CHECKOUT", "REQUIRES", "ACT-VERIFY-ROLLBACK", req1)


def test_phase4_graph_necessity_counterfactual_change_edges(integration_client):
    service = CounterfactualSimulationService(integration_client)
    before = service.simulate("MIG-203", [{"op": "rollback_change", "change_id": "MIG-203"}])
    assert before["delta"]["systems_no_longer_exposed"]
    changed = {"valid_from": "2026-10-16T14:03:00+05:30", "confidence": 1.0, "source_ref_id": "DS-GIT"}
    affects = {"valid_from": "2026-10-16T14:03:00+05:30", "confidence": 0.9}
    try:
        delete_relationship(integration_client, "MIG-203", "CHANGED", "SYS-PRICING-DB")
        delete_relationship(integration_client, "MIG-203", "AFFECTS", "SYS-PRICING-API")
        degraded = CounterfactualSimulationService(integration_client).simulate("MIG-203", [{"op": "rollback_change", "change_id": "MIG-203"}])
        assert degraded["canonical_result"]["blast_radius"]["impacted"] == []
        assert degraded["counterfactual_result"]["blast_radius"]["impacted"] == []
    finally:
        upsert_relationship(integration_client, "MIG-203", "CHANGED", "SYS-PRICING-DB", changed)
        upsert_relationship(integration_client, "MIG-203", "AFFECTS", "SYS-PRICING-API", affects)


def test_phase4_graph_necessity_anomaly_shadow_edge(integration_client):
    service = GraphAnomalyService(integration_client)
    assert any(x["rule"] == "FRONTEND_DIRECT_DATABASE" for x in service.detect()["anomalies"])
    props = {"valid_from": "2026-10-10T00:00:00+05:30", "confidence": 0.95}
    try:
        delete_relationship(integration_client, "SYS-ANALYTICS-UI", "DEPENDS_ON", "SYS-PROD-ORDERS-DB")
        assert not any(x["rule"] == "FRONTEND_DIRECT_DATABASE" for x in service.detect()["anomalies"])
    finally:
        upsert_relationship(integration_client, "SYS-ANALYTICS-UI", "DEPENDS_ON", "SYS-PROD-ORDERS-DB", props)
