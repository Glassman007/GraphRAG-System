from __future__ import annotations

import re
import uuid
from fastapi import Request

from backend.app.api_v1.errors import install_error_handlers
from backend.app.api_v1.router import router
from backend.app.graph.registry_api import registry_router

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def install_api_v1(app) -> None:
    @app.middleware("http")
    async def request_correlation(request: Request, call_next):
        incoming = request.headers.get("X-Request-ID")
        request_id = incoming if incoming and _REQUEST_ID_RE.match(incoming) else str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    install_error_handlers(app)
    app.include_router(router)
    app.include_router(registry_router)
