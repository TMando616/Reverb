"""ワーカーの取り出しを、**本物の2トランザクション**で確かめる（ADR-0017）。

``FOR UPDATE SKIP LOCKED`` が効いて、2つのワーカーが同時に拾っても同じ行を取らないこと。
共有の ``db_session``（1接続・savepoint）では再現できないので、自前でエンジンを作り、
後片付けも自分で行う（test_optimistic_lock_race.py と同じ形）。
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.contents.models import Content, ContentStatus
from app.modules.contents.repository import ContentRepository
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.publishing.models import ConversionJob, JobStatus
from app.modules.publishing.repository import ConversionJobRepository
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import PASSWORD, TEST_DATABASE_URL


@pytest.fixture
async def two_queued_jobs() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], set[int]]]:
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    ids: tuple[int, int] | None = None
    try:
        async with sessionmaker() as session:
            user = await UserRepository(session).create(
                email="worker@example.com",
                password_hash=hash_password(PASSWORD),
                display_name="ワーカー",
            )
            project = await ProjectRepository(session).create(name="ワーカー", created_by=user.id)
            ids = (project.id, user.id)
            job_ids: set[int] = set()
            for title in ("1本目", "2本目"):
                content = await ContentRepository(session).create(
                    project_id=project.id,
                    title=title,
                    body_md="",
                    status=ContentStatus.DRAFTING,
                    created_by=user.id,
                )
                job = ConversionJob(
                    project_id=project.id,
                    content_id=content.id,
                    channel="qiita",
                    status=JobStatus.QUEUED.value,
                    requested_by=user.id,
                    source_revision_no=1,
                    profile_snapshot={},
                    model="claude-opus-5-5",
                )
                session.add(job)
                await session.flush()
                job_ids.add(job.id)
            await session.commit()

        yield sessionmaker, job_ids
    finally:
        if ids is not None:
            async with sessionmaker() as cleanup:
                await cleanup.execute(delete(Content).where(Content.project_id == ids[0]))
                await cleanup.execute(delete(Project).where(Project.id == ids[0]))
                await cleanup.execute(delete(User).where(User.id == ids[1]))
                await cleanup.commit()
        await engine.dispose()


async def test_two_workers_claim_different_jobs(
    two_queued_jobs: tuple[async_sessionmaker[AsyncSession], set[int]],
) -> None:
    sessionmaker, job_ids = two_queued_jobs
    now = datetime.now(UTC)

    async with sessionmaker() as first, sessionmaker() as second:
        # 1つ目はロックを持ったまま（commit しない）。2つ目は待たずに次の行へ進む。
        a = await ConversionJobRepository(first).claim_next(now)
        b = await ConversionJobRepository(second).claim_next(now)
        assert a is not None and b is not None
        assert {a.id, b.id} == job_ids

        # 3つ目のワーカーには何も残っていない（2行とも押さえられている）。
        async with sessionmaker() as third:
            assert await ConversionJobRepository(third).claim_next(now) is None
        await first.commit()
        await second.commit()
