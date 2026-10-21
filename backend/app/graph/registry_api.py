"""Read-only tenant-scoped Company Brain discovery (Graph Registry stage 1)."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.app.api_v1.errors import ApiError
from backend.app.api_v1.security import Principal, require
from backend.app.graph.registry import GraphRegistry, GraphNotRegistered, InvalidGraphRegistration

registry_router = APIRouter(prefix="/api/v1/graphs", tags=["Company Brains"])


@registry_router.get("", summary="List registered, authorized Company Brains")
def list_graphs(principal: Principal = Depends(require("READ_GRAPH"))):
    try:
        return GraphRegistry().list_for_tenant(tenant_id=principal.tenant_id)
    except Exception as exc:
        raise ApiError(503, "GRAPH_REGISTRY_UNAVAILABLE", "Company Brain registry is unavailable") from exc


@registry_router.get("/{graph_id}", summary="Read one authorized Company Brain registration")
def graph_detail(graph_id: str, principal: Principal = Depends(require("READ_GRAPH"))):
    try:
        registry = GraphRegistry()
        item = registry.resolve(tenant_id=principal.tenant_id, graph_id=graph_id)
        listed = registry.list_for_tenant(tenant_id=principal.tenant_id)
        return next(row for row in listed["items"] if row["graph_id"] == item["graph_id"])
    except (GraphNotRegistered, ValueError, StopIteration):
        raise ApiError(404, "NOT_FOUND", "Company Brain not found") from None
    except Exception as exc:
        raise ApiError(503, "GRAPH_REGISTRY_UNAVAILABLE", "Company Brain registry is unavailable") from exc


class NewCompanyBrain(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)


@registry_router.post('', status_code=201, summary='Create a dedicated Company Brain for a new source')
def create_company_brain(body: NewCompanyBrain,
                         principal: Principal = Depends(require('MANAGE_INGESTION'))):
    try:
        return GraphRegistry().create_dedicated(tenant_id=principal.tenant_id,
                                                 display_name=body.display_name)
    except InvalidGraphRegistration as exc:
        raise ApiError(422, 'VALIDATION_FAILED', str(exc)) from exc
    except Exception as exc:
        raise ApiError(503, 'GRAPH_CREATION_FAILED', 'Could not create dedicated Company Brain') from exc
