from __future__ import annotations

from typing import Any

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.mutations import upsert_node, upsert_relationship
from backend.app.services.phase6_utils import now_iso, stable_id


class EventLedgerService:
    """Append-oriented structured event writer used by Phase 6 coordination.

    It stores state transitions and provenance only. It never stores model chain-of-thought.
    """

    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def record(
        self,
        event_type: str,
        *,
        about_ids: list[str],
        actor_id: str | None = None,
        summary: str = "",
        occurred_at: str | None = None,
        event_id: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        timestamp = occurred_at or now_iso()
        eid = event_id or stable_id("EVT-P6-", event_type, timestamp, *about_ids, actor_id or "SYSTEM")
        props = {
            "event_type": event_type,
            "occurred_at": timestamp,
            "created_at": timestamp,
            "summary": summary,
            "phase": "6",
            **(properties or {}),
        }
        upsert_node(self.client, "Event", eid, props)
        for target in dict.fromkeys(about_ids):
            upsert_relationship(self.client, eid, "ABOUT", target, {"valid_from": timestamp, "confidence": 1.0})
        if actor_id:
            upsert_relationship(self.client, eid, "PERFORMED_BY", actor_id, {"valid_from": timestamp, "confidence": 1.0})
        return {"id": eid, **props}
