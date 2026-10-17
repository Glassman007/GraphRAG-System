from __future__ import annotations

import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.graph.client import FalkorGraphClient
from backend.app.services.graph_service import GraphService
from backend.app.services.claim_memory_service import ClaimMemoryService
from backend.app.services.authority_resolution_service import AuthorityResolutionService
from backend.app.services.routing_service import ResponsibilityRoutingService
from backend.app.services.ownership_gap_service import OwnershipGapService
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


def main() -> None:
    client = FalkorGraphClient()
    graph = GraphService(client)
    memory = ClaimMemoryService(client)
    authority = AuthorityResolutionService(client)
    routing = ResponsibilityRoutingService(client)
    orphan = OwnershipGapService(client)

    print("Pricing DB dependents:", graph.get_dependents("SYS-PRICING-DB", max_depth=4))
    print("INC-001 conflict set:", memory.get_conflict_set("INC-001"))
    print("INC-001 resolution:", authority.resolve_subject_conflicts("INC-001"))
    print("Checkout owner:", routing.find_owner("SYS-CHECKOUT"))
    print("Pricing API responsibility:", routing.find_responsible_actor("SYS-PRICING-API"))
    print("Pricing DB experts:", routing.find_experts("SYS-PRICING-DB"))
    print("Pricing DB responder ranking:", routing.rank_candidate_responders("SYS-PRICING-DB"))
    print("Legacy promo ownership risk:", orphan.inspect_resource("SYS-LEGACY-PROMO"))
    print("All orphaned/ambiguous resources:", orphan.detect_orphaned_resources())
    print("CRM identity resolution:", EntityResolutionService(client).resolve_source_record("SRCREC-CRM-42"))
    print("INC-001 investigation:", RelationalInvestigationService(client).investigate_incident("INC-001"))
    print("Pricing DB blast radius:", BlastRadiusService(client).analyze("SYS-PRICING-DB"))
    print("INC-001 knowledge gaps:", KnowledgeGapService(client).detect_for_incident("INC-001"))
    print("Q-003 tool routing:", EvidenceAcquisitionService(client).route_question("Q-003"))
    print("Decision replay:", DecisionGenealogyService(client).replay("DEC-INC001-ROLLBACK"))
    print("INC-001 precedents:", StructuralPrecedentService(client).find_precedents("INC-001"))
    print("INC-001 plan:", ConstraintPlanningService(client).plan_for_incident("INC-001"))
    print("MIG-203 rollback simulation:", CounterfactualSimulationService(client).simulate("MIG-203", [{"op":"rollback_change","change_id":"MIG-203"}]))
    print("Graph anomalies:", GraphAnomalyService(client).detect())


if __name__ == "__main__":
    main()
