from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph import queries
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.graph.temporal import public_properties
from backend.app.domain.models import ClaimCreate, HypothesisCreate, QuestionCreate, TaskCreate, ActionCreate, EventCreate


def _node_dict(value: Any) -> dict[str, Any] | Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return public_properties(value)
    if hasattr(value, "properties"):
        data = public_properties(value.properties)
        labels = getattr(value, "labels", None)
        if labels:
            data["_labels"] = list(labels) if not isinstance(labels, str) else [labels]
        return data
    return value


def _rows(result) -> list[list[Any]]:
    return [[_node_dict(cell) for cell in row] for row in result.result_set]


class GraphService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def get_entity(self, entity_id: str):
        rows = _rows(queries.get_entity(self.client, entity_id))
        return rows[0][0] if rows else None

    def get_neighbors(self, entity_id: str):
        return _rows(queries.get_neighbors(self.client, entity_id))

    def find_paths(self, source_id: str, target_id: str, max_depth: int = 4):
        return queries.find_paths(self.client, source_id, target_id, max_depth).result_set

    def get_dependencies(self, entity_id: str, max_depth: int = 4):
        return _rows(queries.get_dependencies(self.client, entity_id, max_depth))

    def get_dependents(self, entity_id: str, max_depth: int = 4):
        return _rows(queries.get_dependents(self.client, entity_id, max_depth))

    def get_owner(self, entity_id: str, as_of: str | None = None):
        return _rows(queries.get_owner(self.client, entity_id, as_of))

    def get_responsible_people(self, entity_id: str):
        return _rows(queries.get_responsible_people(self.client, entity_id))

    def get_experts(self, entity_id: str):
        return _rows(queries.get_experts(self.client, entity_id))

    def get_claims(self, subject_id: str):
        return _rows(queries.get_claims(self.client, subject_id))

    def get_evidence(self, subject_id: str):
        return _rows(queries.get_evidence(self.client, subject_id))

    def get_conflicts(self, subject_id: str):
        return _rows(queries.get_conflicts(self.client, subject_id))

    def get_policies(self, subject_id: str):
        return _rows(queries.get_policies(self.client, subject_id))

    def get_history(self, subject_id: str):
        return _rows(queries.get_history(self.client, subject_id))

    def get_incident_context(self, incident_id: str) -> dict[str, Any]:
        return {
            "incident": self.get_entity(incident_id),
            "claims": self.get_claims(incident_id),
            "evidence": self.get_evidence(incident_id),
            "conflicts": self.get_conflicts(incident_id),
            "history": self.get_history(incident_id),
        }

    def create_claim(self, item: ClaimCreate):
        upsert_node(self.client, "Claim", item.id, item.model_dump(exclude={"subject_id", "asserted_by_id"}))
        upsert_relationship(self.client, item.id, "ABOUT", item.subject_id, {"valid_from": item.created_at, "confidence": 1.0})
        if item.asserted_by_id:
            upsert_relationship(self.client, item.id, "ASSERTED_BY", item.asserted_by_id, {"valid_from": item.created_at, "confidence": 1.0})
        if item.source_ref_id:
            upsert_relationship(self.client, item.id, "DERIVED_FROM", item.source_ref_id, {"valid_from": item.created_at, "confidence": 1.0})
        return self.get_entity(item.id)

    def create_hypothesis(self, item: HypothesisCreate):
        upsert_node(self.client, "Hypothesis", item.id, item.model_dump(exclude={"subject_id"}))
        upsert_relationship(self.client, item.id, "ABOUT", item.subject_id, {"valid_from": item.created_at, "confidence": 1.0})
        return self.get_entity(item.id)

    def create_question(self, item: QuestionCreate):
        upsert_node(self.client, "Question", item.id, item.model_dump(exclude={"subject_id"}))
        upsert_relationship(self.client, item.id, "ABOUT", item.subject_id, {"valid_from": item.created_at, "confidence": 1.0})
        return self.get_entity(item.id)

    def create_task(self, item: TaskCreate):
        upsert_node(self.client, "Task", item.id, item.model_dump(exclude={"subject_id", "assigned_to_id"}))
        upsert_relationship(self.client, item.id, "ABOUT", item.subject_id, {"valid_from": item.created_at, "confidence": 1.0})
        if item.assigned_to_id:
            upsert_relationship(self.client, item.id, "ASSIGNED_TO", item.assigned_to_id, {"valid_from": item.created_at, "confidence": 1.0})
        return self.get_entity(item.id)

    def create_action(self, item: ActionCreate):
        upsert_node(self.client, "Action", item.id, item.model_dump(exclude={"subject_id"}))
        upsert_relationship(self.client, item.id, "ABOUT", item.subject_id, {"valid_from": item.created_at, "confidence": 1.0})
        return self.get_entity(item.id)

    def create_event(self, item: EventCreate):
        props = {"event_type": item.event_type.value, "occurred_at": item.occurred_at, "created_at": item.occurred_at, "summary": item.summary, **item.properties}
        upsert_node(self.client, "Event", item.id, props)
        for target_id in item.about_ids:
            upsert_relationship(self.client, item.id, "ABOUT", target_id, {"valid_from": item.occurred_at, "confidence": 1.0})
        if item.performed_by_id:
            upsert_relationship(self.client, item.id, "PERFORMED_BY", item.performed_by_id, {"valid_from": item.occurred_at, "confidence": 1.0})
        return self.get_entity(item.id)
