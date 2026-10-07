"""``content_tags`` の複合 FK のテスト（content-pipeline design.md §3-3・§11）。

Service を通さずに行を直接入れて、**DB の制約だけで**企画をまたぐタグ付けが止まることを
確かめる。Service 側の確認（422）が漏れたときの最後の砦が効いているかどうか。
"""

import pytest
from app.modules.auth.models import User
from app.modules.contents.models import Content, ContentStatus, ContentTag, Tag
from app.modules.projects.repository import ProjectRepository
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user


@pytest.fixture
async def author(db_session: AsyncSession) -> User:
    return await create_user(db_session, "author@example.com")


async def _content_and_tag(
    db_session: AsyncSession, author: User, *, tag_project_differs: bool
) -> tuple[Content, Tag, int]:
    repo = ProjectRepository(db_session)
    mine = await repo.create(name="こちら", created_by=author.id)
    other = await repo.create(name="あちら", created_by=author.id)
    content = Content(
        project_id=mine.id,
        title="ネタ",
        body_md="",
        status=ContentStatus.INBOX.value,
        created_by=author.id,
    )
    tag_project = other.id if tag_project_differs else mine.id
    tag = Tag(project_id=tag_project, name="Python", name_key="python")
    db_session.add_all([content, tag])
    await db_session.flush()
    return content, tag, mine.id


async def test_same_project_tagging_is_accepted(db_session: AsyncSession, author: User) -> None:
    content, tag, project_id = await _content_and_tag(db_session, author, tag_project_differs=False)

    db_session.add(ContentTag(content_id=content.id, tag_id=tag.id, project_id=project_id))
    await db_session.flush()


async def test_cross_project_tagging_is_rejected_by_the_database(
    db_session: AsyncSession, author: User
) -> None:
    content, tag, project_id = await _content_and_tag(db_session, author, tag_project_differs=True)

    # project_id をコンテンツ側に合わせても、タグ側の (tag_id, project_id) が存在しない。
    db_session.add(ContentTag(content_id=content.id, tag_id=tag.id, project_id=project_id))
    with pytest.raises(IntegrityError, match="fk_content_tags_tag"):
        await db_session.flush()


async def test_project_id_matching_only_the_tag_is_rejected(
    db_session: AsyncSession, author: User
) -> None:
    content, tag, _ = await _content_and_tag(db_session, author, tag_project_differs=True)

    # 逆にタグ側に合わせると、今度はコンテンツ側の FK が落とす。どちらに寄せても通らない。
    db_session.add(ContentTag(content_id=content.id, tag_id=tag.id, project_id=tag.project_id))
    with pytest.raises(IntegrityError, match="fk_content_tags_content"):
        await db_session.flush()
