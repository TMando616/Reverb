"""Qiita API クライアントのテスト（publishing design.md §10-5・§15）。実際の API は呼ばない。"""

import json

import httpx
import pytest
from app.channels.qiita import QiitaClient
from app.modules.publishing.ports import (
    QiitaAuthError,
    QiitaError,
    QiitaItemInput,
    QiitaNotFoundError,
    QiitaRateLimitedError,
    QiitaRejectedError,
    QiitaUnavailableError,
)

TOKEN = "qiita-secret-token"
ITEM = QiitaItemInput(title="タイトル", body="# 本文", tags=["Python", "FastAPI"], private=True)


def _client(handler: httpx.MockTransport) -> QiitaClient:
    return QiitaClient(transport=handler)


async def test_create_item_sends_the_expected_payload() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"id": "abc123", "url": "https://qiita.com/u/items/abc123"})

    ref = await _client(httpx.MockTransport(handler)).create_item(TOKEN, ITEM)

    assert (ref.id, ref.url) == ("abc123", "https://qiita.com/u/items/abc123")
    request = seen[0]
    assert (request.method, request.url.path) == ("POST", "/api/v2/items")
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert json.loads(request.content) == {
        "title": "タイトル",
        "body": "# 本文",
        "tags": [{"name": "Python", "versions": []}, {"name": "FastAPI", "versions": []}],
        "private": True,
        "tweet": False,
    }


async def test_update_item_patches_by_id() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "abc123", "url": "https://qiita.com/u/items/abc123"})

    await _client(httpx.MockTransport(handler)).update_item(TOKEN, "abc123", ITEM)

    assert (seen[0].method, seen[0].url.path) == ("PATCH", "/api/v2/items/abc123")
    assert "tweet" not in json.loads(seen[0].content)


async def test_authenticated_user_returns_the_user_name() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/authenticated_user"
        return httpx.Response(200, json={"id": "t_mando_", "name": "まんどぅ"})

    assert await _client(httpx.MockTransport(handler)).authenticated_user(TOKEN) == "t_mando_"


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, QiitaAuthError),
        (403, QiitaAuthError),
        (404, QiitaNotFoundError),
        (400, QiitaRejectedError),
        (422, QiitaRejectedError),
        (429, QiitaRateLimitedError),
        (500, QiitaUnavailableError),
        (503, QiitaUnavailableError),
    ],
)
async def test_status_codes_map_to_port_errors(status: int, error: type[QiitaError]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"message": "Qiita の文言", "type": "x"})

    with pytest.raises(error) as excinfo:
        await _client(httpx.MockTransport(handler)).create_item(TOKEN, ITEM)

    assert TOKEN not in str(excinfo.value)


async def test_rejection_carries_qiitas_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "タグが不正です", "type": "bad_request"})

    with pytest.raises(QiitaRejectedError, match="タグが不正です"):
        await _client(httpx.MockTransport(handler)).create_item(TOKEN, ITEM)


@pytest.mark.parametrize(
    "exc", [httpx.ReadTimeout("slow"), httpx.ConnectError("down")], ids=["timeout", "connect"]
)
async def test_post_is_not_retried_on_transport_errors(exc: Exception) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise exc

    with pytest.raises(QiitaUnavailableError):
        await _client(httpx.MockTransport(handler)).create_item(TOKEN, ITEM)

    assert calls == 1


async def test_post_is_not_retried_on_server_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(502)

    with pytest.raises(QiitaUnavailableError):
        await _client(httpx.MockTransport(handler)).create_item(TOKEN, ITEM)

    assert calls == 1
