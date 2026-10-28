"""API 仕様の結合テスト（tasks.md §7.5）。

``/openapi.json`` が参照でき、公開するエンドポイントが全部載っている
こと。ここが欠けると、BFF（§12）が契約を読めない。
"""

from httpx import AsyncClient

EXPECTED_OPERATIONS = {
    ("/health", "get"),
    ("/auth/login", "post"),
    ("/auth/logout", "post"),
    ("/auth/me", "get"),
    ("/projects", "get"),
    ("/projects", "post"),
    ("/projects/{project_id}", "get"),
    ("/projects/{project_id}/invitations", "post"),
    ("/projects/{project_id}/members", "get"),
    ("/projects/{project_id}/members/{user_id}", "patch"),
    ("/projects/{project_id}/members/{user_id}", "delete"),
    ("/invitations/{token}/accept", "post"),
    ("/projects/{project_id}/contents", "get"),
    ("/projects/{project_id}/contents", "post"),
    ("/projects/{project_id}/contents/{content_id}", "get"),
    ("/projects/{project_id}/contents/{content_id}", "patch"),
    ("/projects/{project_id}/contents/{content_id}", "delete"),
    ("/projects/{project_id}/contents/{content_id}/transition", "post"),
    # content-pipeline
    ("/projects/{project_id}/contents/{content_id}/tags", "put"),
    ("/projects/{project_id}/contents/{content_id}/revisions", "get"),
    ("/projects/{project_id}/contents/{content_id}/revisions/{revision_no}", "get"),
    ("/projects/{project_id}/contents/{content_id}/revisions/{revision_no}/restore", "post"),
    ("/projects/{project_id}/tags", "get"),
    ("/projects/{project_id}/tags", "post"),
    ("/projects/{project_id}/tags/{tag_id}", "patch"),
    ("/projects/{project_id}/tags/{tag_id}", "delete"),
    # publishing
    ("/me/accounts/qiita", "get"),
    ("/me/accounts/qiita", "put"),
    ("/me/accounts/qiita", "delete"),
    ("/channels", "get"),
    ("/projects/{project_id}/contents/{content_id}/channels/{channel}/conversions", "post"),
    ("/projects/{project_id}/contents/{content_id}/conversions", "get"),
    ("/projects/{project_id}/contents/{content_id}/conversions/{job_id}", "get"),
    ("/projects/{project_id}/contents/{content_id}/channels/{channel}", "get"),
    ("/projects/{project_id}/contents/{content_id}/channels/{channel}/draft", "put"),
    ("/projects/{project_id}/contents/{content_id}/channels/{channel}/draft/apply", "post"),
}


async def test_openapi_lists_every_endpoint(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200

    schema = response.json()
    operations = {(path, method) for path, methods in schema["paths"].items() for method in methods}

    # 等号で見る：エンドポイントが増減したらこの一覧を更新する手が必ず入る。
    assert operations == EXPECTED_OPERATIONS
