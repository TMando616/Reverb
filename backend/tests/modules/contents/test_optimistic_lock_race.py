"""楽観ロックの2段目を、**本物の2トランザクション**で確かめる（design.md §3-3）。

ほかのテストは1段目（明示の ``expected_version`` 照合）までしか踏まない。
``version_id_col`` による ``WHERE version = ?`` が実際に0行にマッチし、
``StaleDataError`` が 409 に変換される経路は、接続を2本張らないと再現できない。

このファイルだけは共有の ``db_session`` フィクスチャ（1接続・savepoint）を使わず、
自前でエンジンを作り、後片付けも自分で行う。
"""

from collections.abc import AsyncIterator

import pytest
from app.core.exceptions import VersionConflictError
from app.core.security import hash_password
from app.modules.auth.models import User
from app.modules.auth.repository import UserRepository
from app.modules.contents.models import Content, ContentStatus
from app.modules.contents.repository import ContentRepository
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.conftest import PASSWORD, TEST_DATABASE_URL


@pytest.fixture
async def seeded() -> AsyncIterator[tuple[async_sessionmaker[AsyncSession], int, int, int]]:
    """コミット済みの user / project / content を1組用意し、終わったら消す。"""
    # engine の生成も try の内側に置く。シードで落ちたときに dispose と行の
    # 後片付けを飛ばすと、次回の実行が UNIQUE 違反で始まる。
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    ids: tuple[int, int, int] | None = None
    try:
        async with sessionmaker() as session:
            user = await UserRepository(session).create(
                email="race@example.com",
                password_hash=hash_password(PASSWORD),
                display_name="競合",
            )
            project = await ProjectRepository(session).create(name="競合の企画", created_by=user.id)
            content = await ContentRepository(session).create(
                project_id=project.id,
                title="元のタイトル",
                body_md="",
                status=ContentStatus.INBOX,
                created_by=user.id,
            )
            await session.commit()
            ids = (project.id, content.id, user.id)

        yield sessionmaker, *ids
    finally:
        if ids is not None:
            async with sessionmaker() as cleanup:
                await cleanup.execute(delete(Content).where(Content.id == ids[1]))
                await cleanup.execute(delete(Project).where(Project.id == ids[0]))
                await cleanup.execute(delete(User).where(User.id == ids[2]))
                await cleanup.commit()
        await engine.dispose()


async def test_the_second_writer_loses_at_flush_with_409(
    seeded: tuple[async_sessionmaker[AsyncSession], int, int, int],
) -> None:
    sessionmaker, project_id, content_id, _ = seeded

    async with sessionmaker() as first, sessionmaker() as second:
        # 2人が同じ version を読む。
        mine = await ContentRepository(first).get(content_id, project_id)
        theirs = await ContentRepository(second).get(content_id, project_id)
        assert mine is not None and theirs is not None
        assert mine.version == theirs.version == 1

        mine.title = "先勝ち"
        await ContentRepository(first).flush()
        await first.commit()

        # 2人目は expected_version の照合を通り抜けている（読んだ時点では一致）。
        # 負けるのは flush の WHERE version = 1 が0行になるところ。
        theirs.title = "後出し"
        with pytest.raises(VersionConflictError):
            await ContentRepository(second).flush()
        await second.rollback()

    async with sessionmaker() as check:
        current = await ContentRepository(check).get(content_id, project_id)
        assert current is not None
        assert (current.title, current.version) == ("先勝ち", 2)
