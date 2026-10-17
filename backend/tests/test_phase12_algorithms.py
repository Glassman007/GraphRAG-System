from __future__ import annotations

import pytest

import backend.app.services.company_brain_expertise_service as module
from backend.app.services.company_brain_expertise_service import CompanyBrainExpertiseService
from backend.app.services.phase4_graph import GraphEdge, GraphSnapshot


def snap():
    nodes={
        "P1":{"id":"P1","name":"Riya","_labels":["Entity","Person"]},
        "P2":{"id":"P2","name":"Neha","_labels":["Entity","Person"]},
        "S1":{"id":"S1","name":"Pricing DB","_labels":["Entity","System"]},
        "EE1":{"id":"EE1","status":"VALIDATED","_labels":["Entity","ExpertiseEvidence"]},
    }
    edges=[
        GraphEdge("P1","EXPERT_IN","S1",{"confidence":.9,"valid_from":"2026-01-01T00:00:00+05:30"}),
        GraphEdge("P2","CANDIDATE_EXPERT","S1",{"confidence":.7,"valid_from":"2026-10-01T00:00:00+05:30","source_ref_id":"EE1"}),
    ]
    return GraphSnapshot(nodes,edges)


def test_phase12_company_expertise_uses_existing_canonical_and_candidate_edges(monkeypatch):
    monkeypatch.setattr(module.GraphSnapshot,"load",classmethod(lambda cls,client:snap()))
    result=CompanyBrainExpertiseService(object()).list(as_of="2026-10-17T00:00:00+05:30")
    assert [x["relationship"] for x in result["items"]]==["EXPERT_IN","CANDIDATE_EXPERT"]
    assert result["items"][1]["evidence"]["id"]=="EE1"
    assert result["graph_required"] is True


def test_phase12_company_expertise_respects_temporal_validity(monkeypatch):
    s=snap();s.edges[0]=GraphEdge("P1","EXPERT_IN","S1",{"confidence":.9,"valid_from":"2026-01-01T00:00:00+05:30","valid_until":"2026-10-10T00:00:00+05:30"});s._reindex()
    monkeypatch.setattr(module.GraphSnapshot,"load",classmethod(lambda cls,client:s))
    result=CompanyBrainExpertiseService(object()).list(as_of="2026-10-17T00:00:00+05:30")
    assert all(x["actor"]["id"]!="P1" for x in result["items"])


def test_phase12_company_expertise_is_bounded(monkeypatch):
    monkeypatch.setattr(module.GraphSnapshot,"load",classmethod(lambda cls,client:snap()))
    result=CompanyBrainExpertiseService(object()).list(as_of="2026-10-17T00:00:00+05:30",limit=1)
    assert len(result["items"])==1 and result["total_available"]==2


def test_phase12_company_expertise_rejects_unbounded_limit(monkeypatch):
    monkeypatch.setattr(module.GraphSnapshot,"load",classmethod(lambda cls,client:snap()))
    with pytest.raises(ValueError):CompanyBrainExpertiseService(object()).list(limit=501)
