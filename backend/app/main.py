"""Application factory: create the app, register routers and exception handlers."""

from fastapi import FastAPI

from app.core.exception_handlers import register_exception_handlers
from app.modules.auth.router import router as auth_router
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
    # Remaining module routers are registered here as the foundation spec lands them:
    # app.include_router(contents.router.router)
    return app


app = create_app()
