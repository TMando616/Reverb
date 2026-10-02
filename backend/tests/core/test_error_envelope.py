"""エラー封筒の統一と、5xx の内部文面の非公開（design.md §6-3）。"""

import pytest
from app.core.config import Settings
from app.core.exception_handlers import register_exception_handlers
from app.core.exceptions import AppError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


async def test_unknown_path_uses_the_same_envelope(client: AsyncClient) -> None:
    # FastAPI 既定の {"detail": ...} が漏れると、BFF がこれを「予期しないエラー」に
    # 丸めてしまう（frontend/lib/api/server.ts）。
    response = await client.get("/no-such-path")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not Found"}}


async def test_method_not_allowed_uses_the_same_envelope(client: AsyncClient) -> None:
    response = await client.delete("/health")

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "http_error"


async def test_5xx_message_is_not_leaked() -> None:
    class Boom(AppError):
        status = 500
        code = "internal_error"

    # AppError は任意のメッセージを受け取れるので、内部事情が入ってくる余地がある。
    # 5xx では固定文に差し替える。app は本番と同じハンドラ登録だけを共有する。
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom")
    async def _boom() -> None:
        raise Boom('relation "users" does not exist')

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "internal server error"}
    }


def test_production_rejects_the_default_secret_key() -> None:
    # 本番で SECRET_KEY を渡し忘れたときに、既知の既定値で黙って起動させない。
    with pytest.raises(ValueError, match="SECRET_KEY"):
        Settings(environment="production", secret_key="change-me-in-local")


def test_production_accepts_an_overridden_secret_key() -> None:
    settings = Settings(environment="production", secret_key="something-else")

    assert settings.is_production is True
