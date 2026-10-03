"""ドメイン例外とバリデーション例外を JSON のエラー封筒にマッピングする（design.md §6-3）。

すべてのエラーレスポンスは ``{"error": {"code": ..., "message": ...}}`` の形を取り、
クライアントが2種類の封筒を見ることがないようにする。
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError

logger = logging.getLogger("app.error")


def _envelope(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        if exc.status >= 500:
            # 5xx のメッセージは内部事情（SQL・例外文）を含みうるので外に出さない。
            # 情報はログ側に残す。
            logger.error("unexpected app error: %s", exc, exc_info=exc)
            return JSONResponse(
                status_code=exc.status,
                content=_envelope(exc.code, "internal server error"),
            )
        return JSONResponse(status_code=exc.status, content=_envelope(exc.code, exc.message))

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # 未知パス（404）やメソッド不一致（405）は FastAPI 既定の {"detail": ...} で
        # 返るため、ここで封筒を揃える。揃えないと BFF がこれを「予期しないエラー」に
        # 丸めてしまう（frontend/lib/api/server.ts）。
        code = "not_found" if exc.status_code == 404 else "http_error"
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(code, message),
            headers=getattr(exc, "headers", None),
        )

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

    @app.exception_handler(IntegrityError)
    async def _handle_integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        # UNIQUE / FK 違反。「先に存在を確認してから挿入する」形のコードは、確認と
        # 挿入の間に別のリクエストが入ると必ずここへ来る。500 ではなく 409 が実態に近い
        # （どの制約に当たったかは内部情報なので出さない）。
        logger.warning("integrity error", exc_info=exc)
        return JSONResponse(
            status_code=409,
            content=_envelope("conflict", "resource already exists or violates a constraint"),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # 最後の受け皿。ハンドラ実行中の想定外はここで 500 になる。
        # なお dependency の commit（design.md §4-4）はレスポンス送信後に走るため、
        # そこで失敗した場合はここを通ってもステータスを変えられない。**ログだけが
        # 手がかりになる**ので、握り潰さずに残す。
        logger.error("unhandled exception", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_envelope("internal_error", "internal server error"),
        )
