from __future__ import annotations

from backend.app.graph.client import FalkorGraphClient
from backend.app.graph.temporal import to_epoch_us
from backend.app.services.phase4_graph import GraphSnapshot, has_label


def _available(node: dict, as_of_us: int) -> bool:
    for field in ("observed_at", "occurred_at", "created_at", "valid_from"):
        value = node.get(field)
        if value is not None:
            return to_epoch_us(value) <= as_of_us
    return True


class DecisionGenealogyService:
    def __init__(self, client: FalkorGraphClient):
        self.client = client

    def replay(self, decision_id: str, *, as_of: str | None = None) -> dict | None:
        snapshot = GraphSnapshot.load(self.client)
        decision = snapshot.node(decision_id)
        if decision is None or not has_label(decision, "Decision"):
            return None
        decision_time = as_of or decision.get("created_at") or decision.get("valid_from")
        if not decision_time:
            raise ValueError("Decision has no reconstruction timestamp")
        as_of_us = to_epoch_us(decision_time)

        inputs = []
        for edge in snapshot.edges_from(decision_id, {"BASED_ON"}, as_of=decision_time):
            node = snapshot.node(edge.target)
            if node and _available(node, as_of_us):
                inputs.append({"entity": node, "relation": "BASED_ON", "path": f"{decision_id}-[:BASED_ON]->{edge.target}"})

        approvals = [
            {"actor": snapshot.node(e.target), "path": f"{decision_id}-[:APPROVED_BY]->{e.target}"}
            for e in snapshot.edges_from(decision_id, {"APPROVED_BY"}, as_of=decision_time)
        ]
        producers = [
            {"actor": snapshot.node(e.source), "path": f"{e.source}-[:PRODUCED]->{decision_id}"}
            for e in snapshot.edges_to(decision_id, {"PRODUCED"}, as_of=decision_time)
        ]

        action_links = [e for e in snapshot.edges_to(decision_id, {"ABOUT"}, as_of=decision_time) if has_label(snapshot.node(e.source), "Action")]
        actions = []
        for edge in action_links:
            action = snapshot.node(edge.source) or {}
            actions.append({
                "action": action,
                "role": str(action.get("decision_role") or "RELATED").upper(),
                "path": f"{edge.source}-[:ABOUT]->{decision_id}",
            })

        relevant_ids = {decision_id, *(a["action"].get("id") for a in actions if a.get("action"))}
        events = []
        later_events = []
        for eid, node in snapshot.nodes.items():
            if not has_label(node, "Event"):
                continue
            # Event relevance is structural; temporal filtering decides replay vs later outcome.
            about = {e.target for e in snapshot.edges_from(eid, {"ABOUT"})}
            if not (about & relevant_ids):
                continue
            item = {
                "event": node,
                "about": sorted(about & relevant_ids),
                "actors": [snapshot.node(e.target) for e in snapshot.edges_from(eid, {"PERFORMED_BY"}) if snapshot.node(e.target)],
            }
            if _available(node, as_of_us):
                events.append(item)
            else:
                later_events.append(item)
        events.sort(key=lambda x: (to_epoch_us(x["event"].get("occurred_at") or x["event"].get("created_at")), str(x["event"].get("id"))))
        later_events.sort(key=lambda x: (to_epoch_us(x["event"].get("occurred_at") or x["event"].get("created_at")), str(x["event"].get("id"))))

        outcomes = [x for x in events if str(x["event"].get("event_type")) == "OUTCOME_OBSERVED"]
        later_outcomes = [x for x in later_events if str(x["event"].get("event_type")) == "OUTCOME_OBSERVED"]
        policies = [x for x in inputs if has_label(x["entity"], "Policy")]
        claims = [x for x in inputs if has_label(x["entity"], "Claim")]
        evidence = [x for x in inputs if has_label(x["entity"], "Evidence")]
        return {
            "decision": decision,
            "as_of": decision_time,
            "actors": producers,
            "approvals": approvals,
            "claims": claims,
            "evidence": evidence,
            "policies": policies,
            "other_inputs": [x for x in inputs if x not in policies and x not in claims and x not in evidence],
            "alternatives": [a for a in actions if a["role"] == "ALTERNATIVE"],
            "selected_actions": [a for a in actions if a["role"] == "SELECTED"],
            "events": events,
            "outcomes": outcomes,
            "later_outcomes": later_outcomes,
            "later_events_excluded_from_replay": later_events,
            "complete": bool(inputs) and bool(producers or approvals),
            "private_chain_of_thought_stored": False,
            "graph_required": True,
        }
