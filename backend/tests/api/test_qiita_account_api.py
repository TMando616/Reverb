"""``/me/accounts/qiita`` の結合テスト（C5）。Qiita API は fake に差し替える。"""

import pytest
from app.core.crypto import TokenCipher
from app.modules.auth.models import User
from app.modules.publishing.deps import get_qiita_gateway, get_token_cipher
from app.modules.publishing.ports import QiitaAuthError
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user, login
from tests.modules.publishing.conftest import TEST_KEY
from tests.modules.publishing.fakes import FakeQiita

PATH = "/me/accounts/qiita"
TOKEN = "qiita-token-bbbbbbbbbbbbbbbb"


@pytest.fixture
def qiita(app: FastAPI) -> FakeQiita:
    # 鍵は環境変数（CI には無い）に頼らず、テスト用の固定鍵を差し込む。
    fake = FakeQiita()
    app.dependency_overrides[get_qiita_gateway] = lambda: fake
    app.dependency_overrides[get_token_cipher] = lambda: TokenCipher([TEST_KEY])
    return fake


async def test_register_show_and_delete(
    owner_client: AsyncClient, qiita: FakeQiita, owner: User
) -> None:
    assert (await owner_client.get(PATH)).json() == {
        "registered": False,
        "external_user_id": None,
    }

    put = await owner_client.put(PATH, json={"token": f"  {TOKEN}  "})
    assert put.status_code == 200, put.text
    assert put.json() == {"registered": True, "external_user_id": "t_mando_"}
    assert TOKEN not in put.text
    assert qiita.tokens_seen == [TOKEN]  # 前後の空白は落としてから問い合わせる

    shown = await owner_client.get(PATH)
    assert shown.json() == {"registered": True, "external_user_id": "t_mando_"}
    assert TOKEN not in shown.text

    assert (await owner_client.delete(PATH)).status_code == 204
    assert (await owner_client.get(PATH)).json()["registered"] is False


async def test_rejected_token_is_422(owner_client: AsyncClient, qiita: FakeQiita) -> None:
    qiita.fail_with = QiitaAuthError("Unauthorized")

    response = await owner_client.put(PATH, json={"token": TOKEN})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_qiita_token"


async def test_empty_token_is_a_validation_error(
    owner_client: AsyncClient, qiita: FakeQiita
) -> None:
    response = await owner_client.put(PATH, json={"token": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_demo_cannot_register(
    client: AsyncClient, db_session: AsyncSession, qiita: FakeQiita
) -> None:
    await create_user(db_session, "demo@example.com", is_demo=True)
    await login(client, "demo@example.com")

    assert (await client.put(PATH, json={"token": TOKEN})).status_code == 403
    assert (await client.get(PATH)).status_code == 200


async def test_requires_login(client: AsyncClient, qiita: FakeQiita) -> None:
    assert (await client.get(PATH)).status_code == 401
