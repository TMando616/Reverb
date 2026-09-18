"""アプリケーションファクトリ：app を生成し、router と例外ハンドラを登録する。"""

from fastapi import FastAPI

from app.core.exception_handlers import register_exception_handlers
from app.modules.auth.router import router as auth_router
from app.modules.contents.router import router as contents_router
from app.modules.projects.router import invitations_router
from app.modules.projects.router import router as projects_router


def create_app() -> FastAPI:
    app = FastAPI(title="Reverb API", version="0.1.0")
    register_exception_handlers(app)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(projects_router)
    app.include_router(invitations_router)
    app.include_router(contents_router)
    return app


app = create_app()
