"""エラー封筒の統一と、5xx の内部文面の非公開（design.md §6-3）。"""

import pytest
from app.core.config import Settings
from app.core.exception_handlers import register_exception_handlers
from app.core.exceptions import AppError
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError


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


async def test_an_unexpected_exception_does_not_leak_its_message() -> None:
    # AppError ではない生の例外（catch-all の経路）。ここが一番「内部事情が
    # そのまま出る」危険のあるところ。
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/raw-boom")
    async def _raw_boom() -> None:
        raise ValueError('password_hash="$argon2id$v=19$..."')

    # Starlette は catch-all ハンドラの応答を返したうえで例外を再送出する
    # （サーバー側でログを残せるように）。テストクライアントでは握り潰して応答を見る。
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/raw-boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": {"code": "internal_error", "message": "internal server error"}
    }


async def test_integrity_error_becomes_409() -> None:
    # 「存在を確認してから挿入」の競合。500 ではなく 409 にする。
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/duplicate")
    async def _duplicate() -> None:
        raise IntegrityError("INSERT ...", {}, Exception('duplicate key value "users_email_key"'))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.get("/duplicate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"
    # 制約名のような内部情報は出さない。
    assert "users_email_key" not in response.text


def test_docs_are_closed_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    """本番では OpenAPI と docs を出さない。ブラウザは BFF 経由でしか届かない
    （ADR-0014）ので、内部 API の形を外に置く理由が無い。
    """
    from app.core import config
    from app.main import create_app

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: config.Settings(environment="production", secret_key="x" * 32),
    )
    monkeypatch.setattr("app.main.get_settings", config.get_settings)

    app = create_app()

    assert (app.openapi_url, app.docs_url, app.redoc_url) == (None, None, None)


def test_docs_are_open_outside_production() -> None:
    from app.main import create_app

    app = create_app()

    assert app.openapi_url == "/openapi.json"
