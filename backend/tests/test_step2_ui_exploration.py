"""Deterministic checks for Step 2 tenant-scoped browse/search behavior."""
from backend.app.api_v1.application import ExternalApiApplication
from backend.app.services.phase4_graph import GraphSnapshot,GraphEdge


def sample_app():
    nodes={
        "INC-1":{"id":"INC-1","name":"Checkout interrupted","description":"Payments stopped","status":"OPEN","_labels":["Entity","Incident"]},
        "INC-2":{"id":"INC-2","name":"Warehouse incident","status":"RESOLVED","_labels":["Entity","Incident"]},
        "SYS-1":{"id":"SYS-1","name":"Pricing Database","_labels":["Entity","System"]},
        "SYS-2":{"id":"SYS-2","name":"Warehouse Scanner","_labels":["Entity","System"]},
        "PERSON-1":{"id":"PERSON-1","name":"Anaya Sethi","_labels":["Entity","Person"]},
    }
    snap=GraphSnapshot(nodes,[GraphEdge("INC-1","AFFECTS","SYS-1",{}),GraphEdge("INC-2","AFFECTS","SYS-2",{})])
    app=ExternalApiApplication.__new__(ExternalApiApplication)
    app.snapshot=lambda: snap
    return app


def test_search_matches_name_description_id_and_related_system():
    app=sample_app()
    for query in ("checkout","payments","INC-1","pricing database"):
        assert [n['id'] for n in app.page(labels={"Incident"},search=query)['items']]==['INC-1']


def test_filters_are_applied_before_pagination():
    app=sample_app()
    result=app.page(labels={"Incident"},limit=1)
    assert result['has_more'] and result['next_cursor']
    next_page=app.page(labels={"Incident"},limit=1,cursor=result['next_cursor'])
    assert next_page['items'][0]['id']=='INC-2'
    assert [n['id'] for n in app.page(labels={"Incident"},status="resolved",search="scanner")['items']]==['INC-2']


def test_organization_browse_filter_is_canonical():
    app=sample_app()
    assert [n['id'] for n in app.page(labels={"Person"},search="Anaya")['items']]==['PERSON-1']
    assert app.page(labels={"System"},search="Anaya")['items']==[]
