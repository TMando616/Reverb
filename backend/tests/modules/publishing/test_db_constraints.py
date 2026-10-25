"""publishing の部分 UNIQUE と複合 FK のテスト（publishing design.md §3-3）。

Service を通さずに行を直接入れて、**DB の制約だけで**二重実行・二重公開・企画をまたぐ
参照が止まることを確かめる。Service 側の確認が漏れたときの最後の砦。
"""

from datetime import UTC, datetime

import pytest
from app.modules.auth.models import User
from app.modules.contents.models import Content, ContentStatus
from app.modules.projects.repository import ProjectRepository
from app.modules.publishing.models import ConversionJob, JobStatus, Publication
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user


@pytest.fixture
async def author(db_session: AsyncSession) -> User:
    return await create_user(db_session, "author@example.com")


@pytest.fixture
async def content(db_session: AsyncSession, author: User) -> Content:
    project = await ProjectRepository(db_session).create(name="こちら", created_by=author.id)
    row = Content(
        project_id=project.id,
        title="ネタ",
        body_md="本文",
        status=ContentStatus.DRAFTING.value,
        created_by=author.id,
    )
    db_session.add(row)
    await db_session.flush()
    return row


def _job(
    content: Content, author: User, status: JobStatus, project_id: int | None = None
) -> ConversionJob:
    return ConversionJob(
        project_id=project_id or content.project_id,
        content_id=content.id,
        channel="qiita",
        status=status.value,
        requested_by=author.id,
        source_revision_no=1,
        profile_snapshot={},
        model="claude-opus-5-5",
    )


def _publication(content: Content, author: User, external_id: str, **kwargs: object) -> Publication:
    return Publication(
        project_id=content.project_id,
        content_id=content.id,
        channel="qiita",
        external_id=external_id,
        url=f"https://qiita.com/u/items/{external_id}",
        published_by=author.id,
        **kwargs,
    )


@pytest.mark.parametrize("second", [JobStatus.QUEUED, JobStatus.RUNNING])
async def test_two_active_jobs_for_the_same_channel_are_rejected(
    db_session: AsyncSession, content: Content, author: User, second: JobStatus
) -> None:
    db_session.add(_job(content, author, JobStatus.QUEUED))
    await db_session.flush()

    db_session.add(_job(content, author, second))
    with pytest.raises(IntegrityError, match="uq_conversion_jobs_active"):
        await db_session.flush()


async def test_finished_jobs_do_not_block_a_new_one(
    db_session: AsyncSession, content: Content, author: User
) -> None:
    db_session.add_all(
        [
            _job(content, author, JobStatus.SUCCEEDED),
            _job(content, author, JobStatus.FAILED),
            _job(content, author, JobStatus.QUEUED),
        ]
    )
    await db_session.flush()


async def test_a_job_pointing_at_another_projects_content_is_rejected(
    db_session: AsyncSession, content: Content, author: User
) -> None:
    other = await ProjectRepository(db_session).create(name="あちら", created_by=author.id)

    db_session.add(_job(content, author, JobStatus.QUEUED, project_id=other.id))
    with pytest.raises(IntegrityError, match="fk_conversion_jobs_content"):
        await db_session.flush()


async def test_two_active_publications_for_the_same_channel_are_rejected(
    db_session: AsyncSession, content: Content, author: User
) -> None:
    db_session.add(_publication(content, author, "aaa"))
    await db_session.flush()

    db_session.add(_publication(content, author, "bbb"))
    with pytest.raises(IntegrityError, match="uq_publications_active_content_channel"):
        await db_session.flush()


async def test_a_cancelled_publication_does_not_block_republishing(
    db_session: AsyncSession, content: Content, author: User
) -> None:
    # 取消した行は記録として残り、同じ組（同じ外部 ID でも）をもう一度登録できる。
    db_session.add(
        _publication(content, author, "aaa", cancelled_at=datetime.now(UTC), cancelled_by=author.id)
    )
    db_session.add(_publication(content, author, "aaa"))
    await db_session.flush()


async def test_the_same_external_id_cannot_be_registered_twice(
    db_session: AsyncSession, content: Content, author: User
) -> None:
    second = Content(
        project_id=content.project_id,
        title="別のネタ",
        body_md="",
        status=ContentStatus.DRAFTING.value,
        created_by=author.id,
    )
    db_session.add(second)
    db_session.add(_publication(content, author, "aaa"))
    await db_session.flush()

    db_session.add(_publication(second, author, "aaa"))
    with pytest.raises(IntegrityError, match="uq_publications_active_external"):
        await db_session.flush()
