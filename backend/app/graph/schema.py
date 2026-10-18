from __future__ import annotations

from typing import Callable
from backend.app.graph.client import FalkorGraphClient

NODE_LABELS = {
    "Person", "Team", "System", "Project", "Incident", "Deployment", "Change",
    "Document", "Evidence", "Claim", "Hypothesis", "Question", "Decision",
    "Plan", "Task", "Agent", "Action", "Policy", "Commitment", "Event", "Tool",
    "DataSource", "SourceRecord", "WorkBranch", "Checkpoint", "Handoff",
    "Execution", "Finding", "Blocker", "Lock", "ActionAttempt", "CompactionRecord",
    "Outcome", "ExpertiseEvidence", "AgentRun", "AgentStep",
    "ExternalIdentity", "IngestionRun", "Artifact", "IngestionQuarantineRecord",
    "Chunk", "RetrievalExecution", "Investigation",
}

RELATIONSHIP_TYPES = {
    "OWNS", "RESPONSIBLE_FOR", "EXPERT_IN", "MEMBER_OF", "DEPENDS_ON", "AFFECTS",
    "CHANGED", "SUPPORTS", "REFUTES", "CONTRADICTS", "SUPERSEDES", "DERIVED_FROM",
    "BASED_ON", "GOVERNS", "REQUIRES", "BLOCKED_BY", "ASSIGNED_TO", "CLAIMED_BY", "ASSERTED_BY",
    "DISCOVERED_BY", "APPROVED_BY", "PRODUCED", "RESOLVED_BY", "SIMILAR_TO",
    "COMMITTED_TO", "OWED_TO", "PROMISED_BY", "TRIGGERED", "BEFORE", "ABOUT",
    "CONTAINS", "PERFORMED_BY", "PART_OF", "ROOT_CAUSE", "REPRESENTS",
    "CANDIDATE_MATCH", "QUERIES", "HANDOFF_FOR", "PLAN_HAS_TASK", "ADDRESSES", "CANDIDATE_FOR",
    "HAS_EXECUTION", "HAS_CHECKPOINT", "HAS_BRANCH", "LOCKS", "LOCKED_BY",
    "HAS_ATTEMPT", "HAS_COMPACTION", "PROPOSED_ACTION", "VALIDATED_BY",
    "PROMOTED_TO", "HAS_OUTCOME", "CANDIDATE_EXPERT",
    "CAUSE", "MADE_BY", "SATISFIED_BY", "BREACHED_BY", "COLLABORATES_WITH",
    "INGESTED", "NORMALIZED_TO", "RESOLVES_TO", "REFERENCES",
    "DOCUMENTED_BY", "HAS_AGENT_STEP", "HAS_ARTIFACT", "REQUESTED_BY", "FOR_TASK", "USED_SOURCE", "RETURNED", "HAS_RETRIEVAL",
}


def validate_label(label: str) -> str:
    if label not in NODE_LABELS:
        raise ValueError(f"Unsupported node label: {label}")
    return label


def validate_relationship(rel_type: str) -> str:
    if rel_type not in RELATIONSHIP_TYPES:
        raise ValueError(f"Unsupported relationship type: {rel_type}")
    return rel_type


def _ignore_already_exists(fn: Callable[[], object]) -> None:
    try:
        fn()
    except Exception as exc:
        msg = str(exc).lower()
        if any(token in msg for token in ("already", "exists", "duplicate", "indexed")):
            return
        raise


def apply_schema(client: FalkorGraphClient) -> None:
    """Create only the indexes/constraint foundations Phase 2 actually needs."""
    g = client.graph

    # Global canonical identity: each domain node is also labelled :Entity.
    _ignore_already_exists(lambda: g.create_node_range_index("Entity", "tenant_id", "id"))
    _ignore_already_exists(lambda: g.create_node_unique_constraint("Entity", "tenant_id", "id"))

    # Read-path indexes used by deterministic services and later capability phases.
    for label, props in (
        ("Entity", ("id",)),
        ("Claim", ("status",)),
        ("Claim", ("_ts_created_at_us",)),
        ("Event", ("_ts_occurred_at_us",)),
        ("Task", ("status",)),
        ("Execution", ("status",)),
        ("ActionAttempt", ("idempotency_key",)),
        ("Lock", ("lease_until",)),
        ("Action", ("idempotency_key",)),
        ("SourceRecord", ("source_entity_id",)),
        ("Evidence", ("_ts_observed_at_us",)),
        ("Policy", ("_ts_valid_from_us",)),
        ("Commitment", ("due_at",)),
        ("ExternalIdentity", ("source_type", "external_id")),
        ("IngestionRun", ("status",)),
        ("SourceRecord", ("source_key",)),
        ("SourceRecord", ("checksum",)),
        ("Artifact", ("sha256",)),
        ("IngestionQuarantineRecord", ("status",)),
        ("Chunk", ("content_hash",)),
        ("RetrievalExecution", ("status",)),
    ):
        _ignore_already_exists(lambda label=label, props=props: g.create_node_range_index(label, *props))
