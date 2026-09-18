"""共有のテストフィクスチャ。

DB を伴うフィクスチャ（savepoint によるトランザクション分離、design.md §13-1）は
foundation スペックで追加する。M0 のスキャフォールドの段階では app の配線だけを
確認するので、ここではデータベースを必要としない。
"""

from collections.abc import AsyncIterator

import pytest
from app.main import create_app
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
