"""``ContentRepository`` のユニットテスト（design.md §13、tasks.md の F9）。

**実 DB に対して直接叩く。** Service のテストは `FakeContentRepository` を使うが、
fake は企画スコープと論理削除の除外を「手で真似ている」だけなので、本物の
WHERE 句が間違っていても緑になる。ここが唯一その SQL を検証する場所。
"""

import pytest
from app.modules.auth.models import User
from app.modules.contents.models import ContentStatus
from app.modules.contents.repository import ContentRepository, ContentTransitionRepository
from app.modules.projects.repository import ProjectRepository
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user


@pytest.fixture
async def author(db_session: AsyncSession) -> User:
    return await create_user(db_session, "author@example.com")


@pytest.fixture
async def projects(db_session: AsyncSession, author: User) -> tuple[int, int]:
    """別々の2企画。どちらも同じユーザーが作る（スコープ漏れは所有では防げない）。"""
    repo = ProjectRepository(db_session)
    mine = await repo.create(name="こちら", created_by=author.id)
    other = await repo.create(name="あちら", created_by=author.id)
    return mine.id, other.id


async def test_get_is_scoped_to_the_project(
    db_session: AsyncSession, author: User, projects: tuple[int, int]
) -> None:
    mine, other = projects
    repo = ContentRepository(db_session)
    content = await repo.create(
        project_id=mine, title="ネタ", body_md="", status=ContentStatus.INBOX, created_by=author.id
    )

    assert (await repo.get(content.id, mine)) is not None
    # 他企画の id として引くと「無い」。403 ではなく 404 になる根拠（design.md §5-2）。
    assert (await repo.get(content.id, other)) is None


async def test_get_excludes_soft_deleted_rows(
    db_session: AsyncSession, author: User, projects: tuple[int, int]
) -> None:
    mine, _ = projects
    repo = ContentRepository(db_session)
    content = await repo.create(
        project_id=mine, title="消す", body_md="", status=ContentStatus.INBOX, created_by=author.id
    )

    await repo.soft_delete(content)

    assert (await repo.get(content.id, mine)) is None
    # 行そのものは残っている（後続スペックが参照するため・design.md §3-2）。
    remaining = await db_session.scalar(
        select(func.count())
        .select_from(content.__table__)
        .where(content.__table__.c.id == content.id)
    )
    assert remaining == 1


async def test_list_is_scoped_and_filters_status_and_deleted(
    db_session: AsyncSession, author: User, projects: tuple[int, int]
) -> None:
    mine, other = projects
    repo = ContentRepository(db_session)

    inbox = await repo.create(
        project_id=mine, title="受信", body_md="", status=ContentStatus.INBOX, created_by=author.id
    )
    adopted = await repo.create(
        project_id=mine,
        title="採用",
        body_md="",
        status=ContentStatus.ADOPTED,
        created_by=author.id,
    )
    gone = await repo.create(
        project_id=mine, title="削除", body_md="", status=ContentStatus.INBOX, created_by=author.id
    )
    await repo.soft_delete(gone)
    await repo.create(
        project_id=other,
        title="他企画",
        body_md="",
        status=ContentStatus.INBOX,
        created_by=author.id,
    )

    all_mine = await repo.list(mine)
    only_inbox = await repo.list(mine, ContentStatus.INBOX)

    assert {c.id for c in all_mine} == {inbox.id, adopted.id}
    assert [c.id for c in only_inbox] == [inbox.id]


async def test_list_orders_newest_first(
    db_session: AsyncSession, author: User, projects: tuple[int, int]
) -> None:
    mine, _ = projects
    repo = ContentRepository(db_session)
    first = await repo.create(
        project_id=mine, title="1", body_md="", status=ContentStatus.INBOX, created_by=author.id
    )
    second = await repo.create(
        project_id=mine, title="2", body_md="", status=ContentStatus.INBOX, created_by=author.id
    )

    # created_at は同一トランザクション内で同じ値になりうるので、id が tie-break になる。
    assert [c.id for c in await repo.list(mine)] == [second.id, first.id]


async def test_transitions_are_append_only(
    db_session: AsyncSession, author: User, projects: tuple[int, int]
) -> None:
    mine, _ = projects
    contents = ContentRepository(db_session)
    transitions = ContentTransitionRepository(db_session)
    content = await contents.create(
        project_id=mine, title="遷移", body_md="", status=ContentStatus.INBOX, created_by=author.id
    )

    row = await transitions.add(
        content_id=content.id,
        from_status=ContentStatus.INBOX,
        to_status=ContentStatus.ADOPTED,
        actor_user_id=author.id,
    )

    assert (row.from_status, row.to_status) == (ContentStatus.INBOX, ContentStatus.ADOPTED)
    assert row.created_at is not None
