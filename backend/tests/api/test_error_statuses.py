"""エラー系統の結合テスト（tasks.md §7.4）。401 / 403 / 404 / 409 / 422 を各1本以上。

封筒は ``{"error": {"code", "message"}}`` に統一されている（design.md §6-3）ので、
ステータスコードと合わせて ``code`` も確かめる。
"""

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user, login


async def _project_with_content(client: AsyncClient) -> tuple[int, int]:
    project_id = (await client.post("/projects", json={"name": "企画"})).json()["id"]
    content = await client.post(
        f"/projects/{project_id}/contents", json={"title": "ネタ", "body_md": ""}
    )
    return project_id, content.json()["id"]


async def _invite_and_accept(
    owner_client: AsyncClient, project_id: int, email: str, role: str
) -> None:
    """owner が招待を発行し、招待されたユーザーがログインして受諾する。"""
    invitation = await owner_client.post(
        f"/projects/{project_id}/invitations", json={"role": role, "email": email}
    )
    assert invitation.status_code == 201, invitation.text
    # accept_path はフロントの受諾画面のパス（``/invite/{token}``・design.md §9-1）。
    token = invitation.json()["accept_path"].rsplit("/", 1)[-1]

    await login(owner_client, email)
    accepted = await owner_client.post(f"/invitations/{token}/accept", json={})
    assert accepted.status_code == 200, accepted.text


async def test_401_without_a_token(client: AsyncClient) -> None:
    response = await client.get("/projects")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_error"


async def test_401_with_a_garbage_token(client: AsyncClient) -> None:
    response = await client.get("/projects", headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401


async def test_403_when_a_reviewer_writes(
    owner_client: AsyncClient, db_session: AsyncSession
) -> None:
    project_id, content_id = await _project_with_content(owner_client)
    reviewer = await create_user(db_session, "reviewer@example.com", display_name="レビュアー")
    await _invite_and_accept(owner_client, project_id, reviewer.email, "reviewer")

    # 以降は reviewer としてのクライアント。
    created = await owner_client.post(
        f"/projects/{project_id}/contents", json={"title": "書けない", "body_md": ""}
    )
    assert created.status_code == 403
    assert created.json()["error"]["code"] == "forbidden"

    moved = await owner_client.post(
        f"/projects/{project_id}/contents/{content_id}/transition",
        json={"to": "adopted", "expected_version": 1},
    )
    assert moved.status_code == 403


async def test_403_when_a_demo_account_creates_a_project(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    demo = await create_user(db_session, "demo@example.com", display_name="デモ", is_demo=True)
    demo_client = await login(client, demo.email)

    response = await demo_client.post("/projects", json={"name": "作れない"})

    assert response.status_code == 403


async def test_404_for_a_project_you_are_not_a_member_of(
    owner_client: AsyncClient, db_session: AsyncSession
) -> None:
    project_id, content_id = await _project_with_content(owner_client)
    outsider = await create_user(db_session, "outsider@example.com", display_name="部外者")
    outsider_client = await login(owner_client, outsider.email)

    project = await outsider_client.get(f"/projects/{project_id}")
    assert project.status_code == 404
    assert project.json()["error"]["code"] == "not_found"

    # 非メンバーには、コンテンツの存在も伏せる（403 ではなく 404）。
    content = await outsider_client.get(f"/projects/{project_id}/contents/{content_id}")
    assert content.status_code == 404


async def test_409_when_expected_version_is_stale(owner_client: AsyncClient) -> None:
    project_id, content_id = await _project_with_content(owner_client)
    path = f"/projects/{project_id}/contents/{content_id}"
    assert (
        await owner_client.patch(path, json={"title": "先勝ち", "expected_version": 1})
    ).status_code == 200

    late = await owner_client.patch(path, json={"title": "後出し", "expected_version": 1})

    assert late.status_code == 409
    assert late.json()["error"]["code"] == "version_conflict"


async def test_422_for_a_transition_the_table_forbids(owner_client: AsyncClient) -> None:
    project_id, content_id = await _project_with_content(owner_client)

    response = await owner_client.post(
        f"/projects/{project_id}/contents/{content_id}/transition",
        json={"to": "published", "expected_version": 1},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_state_transition"


async def test_422_for_a_malformed_body(owner_client: AsyncClient) -> None:
    project_id, content_id = await _project_with_content(owner_client)

    response = await owner_client.post(
        f"/projects/{project_id}/contents/{content_id}/transition",
        json={"to": "adopted"},  # expected_version が無い
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
