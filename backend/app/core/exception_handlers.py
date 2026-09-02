"""Map domain and validation errors to the JSON error envelope (design.md §6-3).

Every error response has the shape ``{"error": {"code": ..., "message": ...}}``
so clients never see two envelope formats.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError

logger = logging.getLogger("app.error")


def _envelope(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        if exc.status >= 500:
            logger.error("unexpected app error: %s", exc, exc_info=exc)
        return JSONResponse(status_code=exc.status, content=_envelope(exc.code, exc.message))

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, _exc: RequestValidationError
    ) -> JSONResponse:
        # Own handler so input errors share the envelope with domain errors.
        # Clients tell this apart from InvalidStateTransitionError by the code.
        return JSONResponse(
            status_code=422,
            content=_envelope("validation_error", "request validation failed"),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # Last resort. A commit failing after the Service returned surfaces here
        # (design.md §4-4) — log it, never swallow it silently.
        logger.error("unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_envelope("internal_error", "internal server error"),
        )
