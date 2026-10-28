"""アプリケーションファクトリ：app を生成し、router と例外ハンドラを登録する。"""

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import async_session
from app.core.exception_handlers import register_exception_handlers
from app.jobs.worker import run_forever
from app.modules.auth.router import router as auth_router
from app.modules.contents.router import router as contents_router
from app.modules.contents.router import tags_router
from app.modules.projects.router import invitations_router
from app.modules.projects.router import router as projects_router
from app.modules.publishing.deps import get_converter
from app.modules.publishing.router import (
    accounts_router,
    channels_router,
    content_channels_router,
)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """変換ジョブのワーカーを同じプロセスで動かす（ADR-0017）。テストでは止めておく。"""
    task: asyncio.Task[None] | None = None
    if get_settings().run_conversion_worker:
        task = asyncio.create_task(run_forever(async_session, get_converter()))
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def create_app() -> FastAPI:
    # 本番ではスキーマと docs を閉じる。ブラウザは BFF 経由でしか API に届かない
    # 想定（ADR-0014）なので、内部 API の形を外に置く理由が無い。型生成は CI が
    # アプリ内から取る（frontend.md §4）ので、本番の公開は要らない。
    docs_enabled = not get_settings().is_production
    app = FastAPI(
        title="Reverb API",
        version="0.1.0",
        openapi_url="/openapi.json" if docs_enabled else None,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        lifespan=lifespan,
    )
    register_exception_handlers(app)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(invitations_router)
    app.include_router(contents_router)
    app.include_router(tags_router)
    app.include_router(accounts_router)
    app.include_router(channels_router)
    app.include_router(content_channels_router)
    return app


app = create_app()
