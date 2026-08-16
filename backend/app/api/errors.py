"""Unified API error model and exception handlers (spec §18.1/§18.2)."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


class FieldError(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    field_errors: list[FieldError] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""


class AppError(Exception):
    """Domain error carrying a stable machine-readable code and HTTP status."""

    status_code: int = 400
    code: str = "APP_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
        field_errors: list[FieldError] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.details = details or {}
        self.field_errors = field_errors or []


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "PERMISSION_DENIED"


class VersionConflictError(AppError):
    status_code = 409
    code = "RESOURCE_VERSION_CONFLICT"


class ValidationAppError(AppError):
    status_code = 422
    code = "VALIDATION_FAILED"


class ProviderNotConfiguredError(AppError):
    status_code = 503
    code = "PROVIDER_NOT_CONFIGURED"


def _error_response(request: Request, body: ErrorBody, status_code: int) -> JSONResponse:
    body.trace_id = body.trace_id or str(uuid.uuid4())
    # 错误信封遵循 spec §18.1：{ "error": { code, message, ... } }
    return JSONResponse(status_code=status_code, content={"error": body.model_dump()})


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            request,
            ErrorBody(
                code=exc.code,
                message=exc.message,
                field_errors=exc.field_errors,
                details=exc.details,
                trace_id="",
            ),
            exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        field_errors = [
            FieldError(field=".".join(str(part) for part in err["loc"]), message=err["msg"])
            for err in exc.errors()
        ]
        return _error_response(
            request,
            ErrorBody(code="VALIDATION_FAILED", message="请求参数校验失败", field_errors=field_errors),
            422,
        )
