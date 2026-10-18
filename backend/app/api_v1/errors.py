from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, *, details: Any = None):
        super().__init__(message)
        self.status_code = int(status_code)
        self.code = code
        self.message = message
        self.details = details


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", ""))


def error_payload(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details, "request_id": _request_id(request)}}


def install_error_handlers(app) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status_code, content=error_payload(request, exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/v1/"):
            return JSONResponse(status_code=422, content=error_payload(request, "VALIDATION_FAILED", "Request validation failed.", exc.errors()))
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith("/api/v1/"):
            mapping = {400:"INVALID_REQUEST",401:"UNAUTHORIZED",403:"FORBIDDEN",404:"NOT_FOUND",409:"CONFLICT",422:"VALIDATION_FAILED",429:"RATE_LIMITED",503:"DEPENDENCY_UNAVAILABLE"}
            detail = exc.detail
            message = detail if isinstance(detail, str) else "Request failed."
            return JSONResponse(status_code=exc.status_code, content=error_payload(request, mapping.get(exc.status_code,"INTERNAL_ERROR"), message, None if isinstance(detail,str) else detail))
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=getattr(exc, "headers", None))
