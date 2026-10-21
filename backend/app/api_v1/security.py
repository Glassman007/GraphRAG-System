from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from typing import Callable

from fastapi import Header, Request

from backend.app.api_v1.errors import ApiError
from backend.app.config import Settings
from backend.app.graph.client import FalkorGraphClient

READ_PERMISSIONS = {"READ_GRAPH", "READ_EVIDENCE", "READ_ORG_ANALYTICS"}
ALL_PERMISSIONS = READ_PERMISSIONS | {"CREATE_INVESTIGATION", "CREATE_PLAN", "CLAIM_TASK", "WRITE_FINDING", "PROPOSE_ACTION", "EXECUTE_ACTION", "APPROVE_ACTION", "MANAGE_INGESTION", "ADMIN"}


@dataclass(frozen=True)
class Principal:
    subject: str
    tenant_id: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    graph_id: str | None = None


def _builtins() -> dict[str, Principal]:
    return {
        "test-admin-token": Principal("test-admin", "northstar", ("ADMIN",), frozenset(ALL_PERMISSIONS)),
        "test-reader-token": Principal("test-reader", "northstar", ("READER",), frozenset(READ_PERMISSIONS)),
        "test-operator-token": Principal("test-operator", "northstar", ("OPERATOR",), frozenset(ALL_PERMISSIONS - {"ADMIN", "APPROVE_ACTION", "MANAGE_INGESTION"})),
        "test-asteria-admin-token": Principal("asteria-demo-admin", "asteria", ("ADMIN",), frozenset(ALL_PERMISSIONS)),
        "test-other-admin-token": Principal("other-admin", "other-tenant", ("ADMIN",), frozenset(ALL_PERMISSIONS)),
    }


def _configured_principals() -> dict[str, Principal]:
    environment = os.getenv("GRAPH_HACKS_ENV", "development").strip().lower()
    test_auth_disabled = os.getenv("GRAPH_HACKS_DISABLE_TEST_AUTH") == "1" or environment in {"prod", "production"}
    values = {} if test_auth_disabled else _builtins()
    raw = os.getenv("GRAPH_HACKS_API_PRINCIPALS_JSON", "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            for token, item in parsed.items():
                values[str(token)] = Principal(
                    str(item["subject"]), str(item["tenant_id"]), tuple(item.get("roles") or []), frozenset(item.get("permissions") or []),
                )
        except Exception as exc:
            raise RuntimeError("Invalid GRAPH_HACKS_API_PRINCIPALS_JSON") from exc
    return values


def authenticate(request: Request, authorization: str | None = Header(default=None), x_api_key: str | None = Header(default=None), x_tenant_id: str | None = Header(default=None), x_company_brain_id: str | None = Header(default=None)) -> Principal:
    token = x_api_key
    if authorization:
        parts = authorization.split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
    if not token:
        raise ApiError(401, "UNAUTHORIZED", "Authentication credentials are required.")
    principal = _configured_principals().get(token)
    if principal is None:
        raise ApiError(401, "UNAUTHORIZED", "Invalid authentication credentials.")
    if x_tenant_id and x_tenant_id != principal.tenant_id:
        raise ApiError(403, "TENANT_MISMATCH", "Requested tenant does not match authenticated principal.", details={"principal_tenant": principal.tenant_id})
    if x_company_brain_id:
        # The graph name is never accepted just because it exists in FalkorDB.
        from backend.app.graph.registry import GraphRegistry, GraphNotRegistered, InvalidGraphRegistration
        try:
            GraphRegistry().resolve(tenant_id=principal.tenant_id, graph_id=x_company_brain_id)
        except (GraphNotRegistered, InvalidGraphRegistration) as exc:
            raise ApiError(404, "GRAPH_NOT_AVAILABLE", "Company Brain is not registered for this tenant") from exc
        principal = replace(principal, graph_id=x_company_brain_id)
    request.state.principal = principal
    return principal


def require(*permissions: str) -> Callable:
    def dependency(principal: Principal = __import__("fastapi").Depends(authenticate)) -> Principal:
        if "ADMIN" in principal.permissions:
            return principal
        missing = [p for p in permissions if p not in principal.permissions]
        if missing:
            raise ApiError(403, "FORBIDDEN", "Principal lacks required permission.", details={"required": list(permissions), "missing": missing})
        return principal
    return dependency


def client_for(principal: Principal) -> FalkorGraphClient:
    settings = Settings.from_env().model_copy(update={"tenant_id": principal.tenant_id})
    if principal.graph_id:
        from backend.app.graph.registry import GraphRegistry, GraphNotRegistered
        try:
            return GraphRegistry().client_for_graph(tenant_id=principal.tenant_id,
                                                    graph_id=principal.graph_id, settings=settings)
        except GraphNotRegistered as exc:
            raise ApiError(404, "GRAPH_NOT_AVAILABLE", "Registered Company Brain is unavailable") from exc
    return FalkorGraphClient(settings)
