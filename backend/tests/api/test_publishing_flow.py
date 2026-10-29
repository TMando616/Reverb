"""publishing の結合テスト（C10・publishing design.md §15）。

主経路：トークン登録 → 変換 → ワーカーを1回回す → 原稿 → 編集 → 限定共有で投稿 → 公開済
→ 原稿を直して一般公開で更新 → 公開済み一覧 → 取消で執筆中へ。
加えて 401 / 403 / 404 / 409 / 422 の各系統。Claude API・Qiita API は fake に差し替える。
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from app.core.authorization import Role
from app.core.crypto import TokenCipher
from app.jobs.worker import run_once
from app.modules.auth.models import User
from app.modules.projects.repository import ProjectMemberRepository
from app.modules.publishing.deps import (
    build_conversion_service,
    get_qiita_gateway,
    get_token_cipher,
)
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user, login
from tests.modules.publishing.conftest import TEST_KEY
from tests.modules.publishing.fakes import FakeConverter, FakeQiita


@pytest.fixture
def qiita(app: FastAPI) -> FakeQiita:
    fake = FakeQiita()
    app.dependency_overrides[get_qiita_gateway] = lambda: fake
    app.dependency_overrides[get_token_cipher] = lambda: TokenCipher([TEST_KEY])
    return fake


async def _run_worker(db_session: AsyncSession, converter: FakeConverter) -> bool:
    @asynccontextmanager
    async def sessions() -> AsyncIterator[AsyncSession]:
        yield db_session

    return await run_once(sessions, converter, build=build_conversion_service)


async def _drafting_content(client: AsyncClient) -> tuple[int, str]:
    project_id = (await client.post("/projects", json={"name": "発信"})).json()["id"]
    created = await client.post(
        f"/projects/{project_id}/contents", json={"title": "ECS の話", "body_md": "ハマった"}
    )
    content = created.json()
    base = f"/projects/{project_id}/contents/{content['id']}"
    version = content["version"]
    for to in ("adopted", "drafting"):
        moved = await client.post(
            f"{base}/transition", json={"to": to, "expected_version": version}
        )
        assert moved.status_code == 200, moved.text
        version = moved.json()["version"]
    return project_id, base


async def test_convert_edit_publish_push_and_cancel(
    owner_client: AsyncClient, qiita: FakeQiita, db_session: AsyncSession
) -> None:
    assert (await owner_client.put("/me/accounts/qiita", json={"token": "tkn"})).status_code == 200
    project_id, base = await _drafting_content(owner_client)

    channels = await owner_client.get("/channels")
    qiita_caps = next(c for c in channels.json() if c["code"] == "qiita")
    assert qiita_caps["publish"] == "auto"

    requested = await owner_client.post(f"{base}/channels/qiita/conversions")
    assert requested.status_code == 202, requested.text
    assert requested.json()["status"] == "queued"
    assert (await owner_client.get(f"{base}/channels/qiita")).json()["latest_job"]["status"] == (
        "queued"
    )

    assert await _run_worker(db_session, FakeConverter()) is True

    view = (await owner_client.get(f"{base}/channels/qiita")).json()
    assert view["latest_job"]["status"] == "succeeded"
    assert view["latest_job"]["result_tags"] == ["Python", "FastAPI"]
    assert view["draft"]["title"] == "Qiita 向けタイトル"
    assert view["draft_is_stale"] is False
    history = (await owner_client.get(f"{base}/conversions")).json()
    assert len(history) == 1 and "result_body" not in history[0]

    saved = await owner_client.put(
        f"{base}/channels/qiita/draft",
        json={
            "title": "直したタイトル",
            "body": "直した本文",
            "tags": ["Python", "ECS", "Python"],
            "expected_version": view["draft"]["version"],
        },
    )
    assert saved.status_code == 200, saved.text
    draft = saved.json()
    assert draft["tags"] == ["Python", "ECS"]
    assert draft["edited_after_apply"] is True

    published = await owner_client.post(
        f"{base}/channels/qiita/publish",
        json={"visibility": "private", "expected_draft_version": draft["version"]},
    )
    assert published.status_code == 201, published.text
    publication = published.json()
    assert publication["visibility"] == "private"
    assert qiita.created[0][1].title == "直したタイトル"
    assert (await owner_client.get(base)).json()["status"] == "published"

    pushed = await owner_client.post(
        f"{base}/channels/qiita/push",
        json={"expected_draft_version": draft["version"], "visibility": "public"},
    )
    assert pushed.status_code == 200, pushed.text
    assert pushed.json()["visibility"] == "public"
    assert (await owner_client.get(base)).json()["status"] == "published"

    listed = (await owner_client.get(f"/projects/{project_id}/publications")).json()
    assert [entry["title"] for entry in listed] == ["ECS の話"]
    assert listed[0]["publications"][0]["url"] == publication["url"]

    cancelled = await owner_client.delete(
        f"/projects/{project_id}/publications/{publication['id']}"
    )
    assert cancelled.status_code == 204
    assert (await owner_client.get(base)).json()["status"] == "drafting"
    assert (await owner_client.get(f"/projects/{project_id}/publications")).json() == []


async def test_error_statuses(
    owner_client: AsyncClient,
    owner: User,
    qiita: FakeQiita,
    db_session: AsyncSession,
    client: AsyncClient,
) -> None:
    project_id, base = await _drafting_content(owner_client)

    # 404：変換前の原稿
    missing = await owner_client.put(
        f"{base}/channels/qiita/draft",
        json={"title": "t", "body": "b", "tags": [], "expected_version": 1},
    )
    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "not_found")

    # 422：知らないチャネル・まだ変換できないチャネル
    assert (await owner_client.post(f"{base}/channels/unknown/conversions")).status_code == 422
    x = await owner_client.post(f"{base}/channels/x/conversions")
    assert (x.status_code, x.json()["error"]["code"]) == (422, "unsupported_channel")

    # 409：二重実行
    await owner_client.post(f"{base}/channels/qiita/conversions")
    again = await owner_client.post(f"{base}/channels/qiita/conversions")
    assert (again.status_code, again.json()["error"]["code"]) == (409, "conversion_in_progress")
    await _run_worker(db_session, FakeConverter())
    draft = (await owner_client.get(f"{base}/channels/qiita")).json()["draft"]

    # 409：トークン未登録
    no_token = await owner_client.post(
        f"{base}/channels/qiita/publish",
        json={"visibility": "private", "expected_draft_version": draft["version"]},
    )
    assert (no_token.status_code, no_token.json()["error"]["code"]) == (409, "qiita_token_missing")
    await owner_client.put("/me/accounts/qiita", json={"token": "tkn"})

    # 422：Qiita の制約（タグ0個）
    emptied = await owner_client.put(
        f"{base}/channels/qiita/draft",
        json={"title": "t", "body": "b", "tags": [], "expected_version": draft["version"]},
    )
    version = emptied.json()["version"]
    no_tags = await owner_client.post(
        f"{base}/channels/qiita/publish",
        json={"visibility": "private", "expected_draft_version": version},
    )
    assert (no_tags.status_code, no_tags.json()["error"]["code"]) == (422, "invalid_draft")

    # 409：原稿の版が古い
    stale = await owner_client.post(
        f"{base}/channels/qiita/publish",
        json={"visibility": "private", "expected_draft_version": version - 1},
    )
    assert (stale.status_code, stale.json()["error"]["code"]) == (409, "version_conflict")

    # 403：editor は変換できるが公開できない
    editor = await create_user(db_session, "editor@example.com")
    await ProjectMemberRepository(db_session).add(
        project_id=project_id, user_id=editor.id, role=Role.EDITOR
    )
    await login(client, "editor@example.com")
    forbidden = await client.post(
        f"{base}/channels/qiita/publish",
        json={"visibility": "private", "expected_draft_version": version},
    )
    assert (forbidden.status_code, forbidden.json()["error"]["code"]) == (403, "forbidden")
    assert qiita.created == []

    # 401：未ログイン
    client.headers.pop("Authorization")
    assert (await client.get(f"{base}/channels/qiita")).status_code == 401
