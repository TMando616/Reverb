"""Qiita API v2 のクライアント（publishing design.md §10）。

- タイムアウト 15秒、**再試行しない。** 投稿（POST）は冪等でなく、再試行は二重投稿の原因になる
- ステータスはポートの例外に写す（§10-5）。Service がそれを HTTP のエラーコードに写す
- トークンは Authorization ヘッダにだけ載せる。例外・ログに出さない
"""

import logging
from typing import Any

import httpx

from app.modules.publishing.ports import (
    QiitaAuthError,
    QiitaItemInput,
    QiitaItemRef,
    QiitaNotFoundError,
    QiitaRateLimitedError,
    QiitaRejectedError,
    QiitaUnavailableError,
)

logger = logging.getLogger("app.channels.qiita")

BASE_URL = "https://qiita.com"
TIMEOUT_SECONDS = 15.0


class QiitaClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        # transport はテストで httpx.MockTransport を差し込むため。
        self._transport = transport

    async def authenticated_user(self, token: str) -> str:
        data = await self._request("GET", "/api/v2/authenticated_user", token)
        return str(data["id"])

    async def create_item(self, token: str, item: QiitaItemInput) -> QiitaItemRef:
        payload = {**_item_payload(item), "tweet": False}
        data = await self._request("POST", "/api/v2/items", token, json=payload)
        return QiitaItemRef(id=str(data["id"]), url=str(data["url"]))

    async def update_item(self, token: str, item_id: str, item: QiitaItemInput) -> QiitaItemRef:
        data = await self._request(
            "PATCH", f"/api/v2/items/{item_id}", token, json=_item_payload(item)
        )
        return QiitaItemRef(id=str(data["id"]), url=str(data["url"]))

    async def _request(
        self, method: str, path: str, token: str, *, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=BASE_URL, timeout=TIMEOUT_SECONDS, transport=self._transport
            ) as client:
                response = await client.request(
                    method, path, json=json, headers={"Authorization": f"Bearer {token}"}
                )
        except httpx.TimeoutException:
            raise QiitaUnavailableError("qiita timed out") from None
        except httpx.TransportError:
            raise QiitaUnavailableError("could not reach qiita") from None

        status = response.status_code
        if status in (200, 201):
            body: dict[str, Any] = response.json()
            return body
        message = _error_message(response)
        logger.info("qiita %s %s -> %s", method, path, status)
        if status in (401, 403):
            raise QiitaAuthError(message)
        if status == 404:
            raise QiitaNotFoundError(message)
        if status == 429:
            raise QiitaRateLimitedError(message)
        if status in (400, 422):
            raise QiitaRejectedError(message)
        raise QiitaUnavailableError(f"qiita returned {status}")


def _item_payload(item: QiitaItemInput) -> dict[str, Any]:
    return {
        "title": item.title,
        "body": item.body,
        # versions はバージョン付きタグ用。使わないので空。
        "tags": [{"name": name, "versions": []} for name in item.tags],
        "private": item.private,
    }


def _error_message(response: httpx.Response) -> str:
    """Qiita のエラー本文 ``{"message", "type"}`` から message を取り出す。"""
    try:
        data = response.json()
    except ValueError:
        return f"qiita returned {response.status_code}"
    message = data.get("message") if isinstance(data, dict) else None
    if isinstance(message, str):
        return message[:500]
    return f"qiita returned {response.status_code}"
