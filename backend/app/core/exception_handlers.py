"""ドメイン例外とバリデーション例外を JSON のエラー封筒にマッピングする（design.md §6-3）。

すべてのエラーレスポンスは ``{"error": {"code": ..., "message": ...}}`` の形を取り、
クライアントが2種類の封筒を見ることがないようにする。
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
        # 専用ハンドラを置くことで、入力エラーもドメイン例外と同じ封筒を共有する。
        # クライアントは code で InvalidStateTransitionError と区別できる。
        return JSONResponse(
            status_code=422,
            content=_envelope("validation_error", "request validation failed"),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # 最後の受け皿。Service が正常に戻った後の commit 失敗もここに現れる
        # （design.md §4-4）— 必ずログに残し、黒く握り潰さない。
        logger.error("unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_envelope("internal_error", "internal server error"),
        )
