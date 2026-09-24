"""主経路の結合テスト（tasks.md §7.3）。

ログイン → 企画作成 → コンテンツ登録 → ``inbox → adopted → drafting`` を、
実 DB と実ルーターを通して1本で確かめる。
"""

from httpx import AsyncClient


async def test_login_create_project_content_and_move_to_drafting(owner_client: AsyncClient) -> None:
    project = await owner_client.post("/projects", json={"name": "Reverb 立ち上げ"})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    assert project.json()["role"] == "owner"

    created = await owner_client.post(
        f"/projects/{project_id}/contents",
        json={"title": "状態遷移の記事", "body_md": "下書き"},
    )
    assert created.status_code == 201, created.text
    content = created.json()
    assert (content["status"], content["version"]) == ("inbox", 1)

    path = f"/projects/{project_id}/contents/{content['id']}/transition"
    adopted = await owner_client.post(path, json={"to": "adopted", "expected_version": 1})
    assert adopted.status_code == 200, adopted.text
    assert (adopted.json()["status"], adopted.json()["version"]) == ("adopted", 2)

    drafting = await owner_client.post(path, json={"to": "drafting", "expected_version": 2})
    assert drafting.status_code == 200, drafting.text
    assert (drafting.json()["status"], drafting.json()["version"]) == ("drafting", 3)

    # 一覧・単体取得にも、遷移後の状態がそのまま出る。
    listed = await owner_client.get(
        f"/projects/{project_id}/contents", params={"status": "drafting"}
    )
    assert [row["id"] for row in listed.json()] == [content["id"]]

    fetched = await owner_client.get(f"/projects/{project_id}/contents/{content['id']}")
    assert fetched.json()["status"] == "drafting"


async def test_logout_revokes_the_token(owner_client: AsyncClient) -> None:
    assert (await owner_client.post("/auth/logout")).status_code in (200, 204)

    after = await owner_client.get("/auth/me")
    assert after.status_code == 401
