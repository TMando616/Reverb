"""auth の境界的な振る舞いの結合テスト（レビュー指摘の再発防止）。

実 DB を通す：``normalize_email`` は ``users.email`` の UNIQUE 制約と組みで
「大文字小文字を区別しない一意性」を作っているので、fake では確かめられない。
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import PASSWORD, create_user, login


async def test_login_is_case_insensitive_for_the_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # CLI で大文字混じりのアドレスを登録した人が、小文字で打ってログインできないと
    # 原因の分からない締め出しになる。
    await create_user(db_session, "Owner@Example.com")

    response = await client.post(
        "/auth/login", json={"email": "owner@example.com", "password": PASSWORD}
    )

    assert response.status_code == 200, response.text


async def test_email_is_stored_normalised(db_session: AsyncSession) -> None:
    user = await create_user(db_session, "  MixedCase@Example.COM  ")

    assert user.email == "mixedcase@example.com"


async def test_logout_is_idempotent_and_does_not_401(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    # 期限切れのタブからログアウトしたときに失敗と見えないよう、失効済みの
    # トークンでも 204 を返す（service.logout は冪等）。
    user = await create_user(db_session, "logout@example.com")
    authed = await login(client, user.email)

    first = await authed.post("/auth/logout")
    second = await authed.post("/auth/logout")

    assert first.status_code == 204
    assert second.status_code == 204
    # ただし保護された API は 401 のまま。
    assert (await authed.get("/auth/me")).status_code == 401


async def test_logout_without_a_token_is_still_401(client: AsyncClient) -> None:
    assert (await client.post("/auth/logout")).status_code == 401
