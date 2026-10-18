from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.domain.models import ClaimCreate, EventCreate, EventType


def test_claim_confidence_is_bounded():
    with pytest.raises(ValidationError):
        ClaimCreate(
            id="C-X", statement="x", subject_id="INC-001", confidence=1.1,
            created_at="2026-10-16T00:00:00+05:30",
        )


def test_event_type_is_explicit():
    event = EventCreate(
        id="EVT-X", event_type=EventType.TASK_CREATED,
        occurred_at="2026-10-16T00:00:00+05:30", summary="created", about_ids=["TASK-X"]
    )
    assert event.event_type.value == "TASK_CREATED"
