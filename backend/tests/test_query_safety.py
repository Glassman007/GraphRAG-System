from __future__ import annotations

import pytest

from backend.app.graph.queries import _bounded_depth
from backend.app.graph.schema import validate_label, validate_relationship


def test_whitelist_rejects_arbitrary_label():
    with pytest.raises(ValueError):
        validate_label("Person) MATCH (n) DETACH DELETE n //")


def test_whitelist_rejects_arbitrary_relationship():
    with pytest.raises(ValueError):
        validate_relationship("OWNS]->(x) DELETE x //")


def test_depth_is_bounded():
    assert _bounded_depth(4) == 4
    with pytest.raises(ValueError):
        _bounded_depth(100)
