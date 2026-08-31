"""Map :mod:`app.core.exceptions` to HTTP responses (design.md §6-3)."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    AppError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)

_STATUS_BY_ERROR: dict[type[AppError], int] = {
    NotFoundError: 404,
    PermissionDeniedError: 403,
    ConflictError: 409,
    ValidationError: 422,
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        status = next(
            (s for e, s in _STATUS_BY_ERROR.items() if isinstance(exc, e)),
            500,
        )
        return JSONResponse(
            status_code=status, content={"detail": str(exc) or exc.__class__.__name__}
        )
