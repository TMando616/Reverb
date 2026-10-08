"""content-pipeline の実 DB テスト用の組み立て（content-pipeline design.md §11）。

タグ・絞り込み・リビジョンは SQL（UNIQUE・複合 FK・HAVING・ILIKE・MAX + 1）に
振る舞いが乗っているので、fake ではなく本物の Repository で Service を組み立てる。
"""

from dataclasses import dataclass

import pytest
from app.core.authorization import Actor, ProjectAuthorizer, Role
from app.modules.contents.repository import (
    ContentRepository,
    ContentTagRepository,
    ContentTransitionRepository,
    RevisionRepository,
    TagRepository,
)
from app.modules.contents.service import ContentService, TagService
from app.modules.projects.repository import ProjectMemberRepository, ProjectRepository
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user


@dataclass(frozen=True)
class World:
    contents: ContentService
    tags: TagService
    project: int
    other_project: int
    owner: Actor
    editor: Actor
    reviewer: Actor
    demo: Actor


@pytest.fixture
async def world(db_session: AsyncSession) -> World:
    owner = await create_user(db_session, "owner@example.com")
    editor = await create_user(db_session, "editor@example.com")
    reviewer = await create_user(db_session, "reviewer@example.com")
    demo = await create_user(db_session, "demo@example.com", is_demo=True)

    projects = ProjectRepository(db_session)
    members = ProjectMemberRepository(db_session)
    mine = await projects.create(name="こちら", created_by=owner.id)
    other = await projects.create(name="あちら", created_by=owner.id)
    for project_id in (mine.id, other.id):
        await members.add(project_id=project_id, user_id=owner.id, role=Role.OWNER)
    await members.add(project_id=mine.id, user_id=editor.id, role=Role.EDITOR)
    await members.add(project_id=mine.id, user_id=reviewer.id, role=Role.REVIEWER)
    # owner role であっても demo は閲覧のみ（foundation design.md §5-2）。
    await members.add(project_id=mine.id, user_id=demo.id, role=Role.OWNER)

    authz = ProjectAuthorizer(members)
    tag_repo = TagRepository(db_session)
    return World(
        contents=ContentService(
            contents=ContentRepository(db_session),
            authz=authz,
            transitions=ContentTransitionRepository(db_session),
            tags=tag_repo,
            content_tags=ContentTagRepository(db_session),
            revisions=RevisionRepository(db_session),
        ),
        tags=TagService(tags=tag_repo, authz=authz),
        project=mine.id,
        other_project=other.id,
        owner=Actor(user_id=owner.id, is_demo=False),
        editor=Actor(user_id=editor.id, is_demo=False),
        reviewer=Actor(user_id=reviewer.id, is_demo=False),
        demo=Actor(user_id=demo.id, is_demo=True),
    )
