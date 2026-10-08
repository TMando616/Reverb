"""content-pipeline の結合テスト（content-pipeline design.md §11・tasks.md 4.6）。

主経路：タグ作成 → タグ付きでコンテンツ作成 → 絞り込み → 本文保存2回 → 版一覧（3件）
→ 1版目を復元 → 版一覧（4件・最新が restore）。
加えて、このスペックで増えたエラーコードが封筒どおりに返ること。
"""

from httpx import AsyncClient


async def _project(client: AsyncClient) -> int:
    response = await client.post("/projects", json={"name": "執筆"})
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def test_tag_write_filter_save_and_restore(owner_client: AsyncClient) -> None:
    project_id = await _project(owner_client)
    base = f"/projects/{project_id}"

    tag = await owner_client.post(f"{base}/tags", json={"name": "AWS"})
    assert tag.status_code == 201, tag.text
    tag_id = tag.json()["id"]

    created = await owner_client.post(
        f"{base}/contents",
        json={
            "title": "ECS の話",
            "body_md": "メモ",
            "tag_ids": [tag_id],
            "source_note_path": "01_思いつき\\ECS.md",
        },
    )
    assert created.status_code == 201, created.text
    content = created.json()
    assert content["tags"] == [{"id": tag_id, "name": "AWS"}]
    assert content["source_note_path"] == "01_思いつき/ECS.md"
    await owner_client.post(f"{base}/contents", json={"title": "タグなし"})

    listed = await owner_client.get(f"{base}/contents", params={"tag": tag_id, "q": "ecs"})
    assert [row["id"] for row in listed.json()] == [content["id"]]
    assert "body_md" not in listed.json()[0]

    path = f"{base}/contents/{content['id']}"
    first = await owner_client.patch(path, json={"body_md": "第1稿", "expected_version": 1})
    assert first.status_code == 200, first.text
    second = await owner_client.patch(path, json={"body_md": "第2稿", "expected_version": 2})
    assert second.json()["version"] == 3
    # source_note_path を送らなかった PATCH では消えない
    assert second.json()["source_note_path"] == "01_思いつき/ECS.md"

    revisions = await owner_client.get(f"{path}/revisions")
    assert [(r["revision_no"], r["kind"]) for r in revisions.json()] == [
        (3, "save"),
        (2, "save"),
        (1, "create"),
    ]
    assert "body_md" not in revisions.json()[0]
    assert (await owner_client.get(f"{path}/revisions/1")).json()["body_md"] == "メモ"

    restored = await owner_client.post(f"{path}/revisions/1/restore", json={"expected_version": 3})
    assert restored.status_code == 200, restored.text
    assert (restored.json()["body_md"], restored.json()["version"]) == ("メモ", 4)

    latest = (await owner_client.get(f"{path}/revisions")).json()[0]
    assert (latest["revision_no"], latest["kind"], latest["restored_from_no"]) == (4, "restore", 1)

    tags = await owner_client.get(f"{base}/tags")
    assert tags.json() == [{"id": tag_id, "name": "AWS", "content_count": 1}]


async def test_new_error_codes(owner_client: AsyncClient) -> None:
    project_id = await _project(owner_client)
    other_id = await _project(owner_client)
    base = f"/projects/{project_id}"
    await owner_client.post(f"{base}/tags", json={"name": "AWS"})
    foreign_tag = (
        await owner_client.post(f"/projects/{other_id}/tags", json={"name": "Go"})
    ).json()
    content = (await owner_client.post(f"{base}/contents", json={"title": "t"})).json()

    duplicate = await owner_client.post(f"{base}/tags", json={"name": "aws"})
    assert (duplicate.status_code, duplicate.json()["error"]["code"]) == (409, "tag_name_conflict")

    stale = await owner_client.patch(
        f"{base}/contents/{content['id']}", json={"title": "x", "expected_version": 99}
    )
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "version_conflict")

    invalid = await owner_client.put(
        f"{base}/contents/{content['id']}/tags", json={"tag_ids": [foreign_tag["id"]]}
    )
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (422, "invalid_tag")

    bad_path = await owner_client.patch(
        f"{base}/contents/{content['id']}",
        json={"source_note_path": "../x.md", "expected_version": 1},
    )
    assert (bad_path.status_code, bad_path.json()["error"]["code"]) == (422, "validation_error")

    missing = await owner_client.get(f"{base}/contents/{content['id']}/revisions/99")
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "not_found")

    too_long = await owner_client.get(f"{base}/contents", params={"q": "x" * 101})
    assert too_long.status_code == 422


async def test_tag_and_revision_endpoints_require_auth(client: AsyncClient) -> None:
    for method, url in [
        ("GET", "/projects/1/tags"),
        ("POST", "/projects/1/tags"),
        ("GET", "/projects/1/contents/1/revisions"),
        ("POST", "/projects/1/contents/1/revisions/1/restore"),
        ("PUT", "/projects/1/contents/1/tags"),
    ]:
        response = await client.request(method, url, json={})
        assert response.status_code == 401, (method, url)
