"""タグのテスト（content-pipeline C1・design.md §6-4・tasks.md 2.6）。"""

import pytest
from app.core.exceptions import (
    ForbiddenError,
    InvalidTagError,
    NotFoundError,
    TagNameConflictError,
)
from app.modules.contents.service import MAX_TAGS_PER_CONTENT, tag_name_key
from sqlalchemy.ext.asyncio import AsyncSession

from tests.modules.contents.conftest import World


def test_name_key_folds_case_width_and_surrounding_spaces() -> None:
    assert tag_name_key("Python") == tag_name_key("python") == tag_name_key(" ＰＹＴＨＯＮ ")
    assert tag_name_key("㍿") == "株式会社"


async def test_same_name_in_another_spelling_conflicts(world: World) -> None:
    await world.tags.create(world.owner, world.project, name="Python")

    for spelling in ("python", "ＰＹＴＨＯＮ", " Python "):
        with pytest.raises(TagNameConflictError):
            await world.tags.create(world.editor, world.project, name=spelling)


async def test_same_name_is_allowed_in_another_project(world: World) -> None:
    await world.tags.create(world.owner, world.project, name="Python")

    other = await world.tags.create(world.owner, world.other_project, name="Python")

    assert other.project_id == world.other_project


async def test_the_session_is_usable_after_a_name_conflict(world: World) -> None:
    """UNIQUE 違反は SAVEPOINT の中で起きるので、同じリクエストの後続の書き込みが通る。"""
    await world.tags.create(world.owner, world.project, name="Python")
    with pytest.raises(TagNameConflictError):
        await world.tags.create(world.owner, world.project, name="python")

    created = await world.tags.create(world.owner, world.project, name="Go")

    assert created.id is not None


async def test_rename_is_reflected_on_every_tagged_content(
    world: World, db_session: AsyncSession
) -> None:
    tag = await world.tags.create(world.owner, world.project, name="AWS")
    ids = [
        (
            await world.contents.create(
                world.owner, world.project, title=t, body_md="", tag_ids=[tag.id]
            )
        ).id
        for t in ("a", "b")
    ]

    await world.tags.rename(world.editor, world.project, tag.id, name="Amazon Web Services")
    # identity map に残った Tag を見ないよう、DB から読み直させる。
    db_session.expire_all()

    for content_id in ids:
        fresh = await world.contents.get(world.owner, world.project, content_id)
        assert [t.name for t in fresh.tags] == ["Amazon Web Services"]


async def test_rename_to_an_existing_name_conflicts(world: World) -> None:
    await world.tags.create(world.owner, world.project, name="AWS")
    go = await world.tags.create(world.owner, world.project, name="Go")

    with pytest.raises(TagNameConflictError):
        await world.tags.rename(world.owner, world.project, go.id, name="aws")


async def test_delete_untags_contents_but_keeps_them(
    world: World, db_session: AsyncSession
) -> None:
    tag = await world.tags.create(world.owner, world.project, name="AWS")
    content_id = (
        await world.contents.create(
            world.owner, world.project, title="a", body_md="", tag_ids=[tag.id]
        )
    ).id

    await world.tags.delete(world.owner, world.project, tag.id)
    # expire 後に属性を読むと暗黙のロードになるので、id は先に控えておく。
    db_session.expire_all()

    survived = await world.contents.get(world.owner, world.project, content_id)
    assert survived.tags == []
    assert await world.tags.list(world.owner, world.project) == []


async def test_list_counts_usage(world: World) -> None:
    aws = await world.tags.create(world.owner, world.project, name="AWS")
    go = await world.tags.create(world.owner, world.project, name="Go")
    await world.contents.create(world.owner, world.project, title="a", body_md="", tag_ids=[aws.id])
    await world.contents.create(
        world.owner, world.project, title="b", body_md="", tag_ids=[aws.id, go.id]
    )

    rows = await world.tags.list(world.reviewer, world.project)

    assert [(tag.name, count) for tag, count in rows] == [("AWS", 2), ("Go", 1)]


async def test_set_tags_replaces_the_set(world: World) -> None:
    aws = await world.tags.create(world.owner, world.project, name="AWS")
    go = await world.tags.create(world.owner, world.project, name="Go")
    ci = await world.tags.create(world.owner, world.project, name="CI")
    content = await world.contents.create(
        world.owner, world.project, title="a", body_md="", tag_ids=[aws.id, go.id]
    )
    version = content.version

    updated = await world.contents.set_tags(world.editor, world.project, content.id, [go.id, ci.id])

    assert sorted(t.name for t in updated.tags) == ["CI", "Go"]
    # タグの付け替えは version を進めない（design.md §4）。
    assert updated.version == version


async def test_tags_of_another_project_are_rejected(world: World) -> None:
    foreign = await world.tags.create(world.owner, world.other_project, name="AWS")
    content = await world.contents.create(world.owner, world.project, title="a", body_md="")

    with pytest.raises(InvalidTagError):
        await world.contents.set_tags(world.owner, world.project, content.id, [foreign.id])
    with pytest.raises(InvalidTagError):
        await world.contents.create(
            world.owner, world.project, title="b", body_md="", tag_ids=[foreign.id]
        )
    with pytest.raises(InvalidTagError):
        await world.contents.set_tags(world.owner, world.project, content.id, [999_999])


async def test_more_than_the_limit_is_rejected(world: World) -> None:
    ids = [
        (await world.tags.create(world.owner, world.project, name=f"t{i}")).id
        for i in range(MAX_TAGS_PER_CONTENT + 1)
    ]
    content = await world.contents.create(world.owner, world.project, title="a", body_md="")

    await world.contents.set_tags(world.owner, world.project, content.id, ids[:-1])
    with pytest.raises(InvalidTagError):
        await world.contents.set_tags(world.owner, world.project, content.id, ids)


async def test_reviewer_and_demo_cannot_change_tags(world: World) -> None:
    tag = await world.tags.create(world.owner, world.project, name="AWS")
    content = await world.contents.create(world.owner, world.project, title="a", body_md="")

    for actor in (world.reviewer, world.demo):
        with pytest.raises(ForbiddenError):
            await world.tags.create(actor, world.project, name="Go")
        with pytest.raises(ForbiddenError):
            await world.tags.rename(actor, world.project, tag.id, name="Go")
        with pytest.raises(ForbiddenError):
            await world.tags.delete(actor, world.project, tag.id)
        with pytest.raises(ForbiddenError):
            await world.contents.set_tags(actor, world.project, content.id, [tag.id])
        # 閲覧はできる
        assert len(await world.tags.list(actor, world.project)) == 1


async def test_tag_of_another_project_is_not_found(world: World) -> None:
    foreign = await world.tags.create(world.owner, world.other_project, name="AWS")

    with pytest.raises(NotFoundError):
        await world.tags.rename(world.owner, world.project, foreign.id, name="Go")
    with pytest.raises(NotFoundError):
        await world.tags.delete(world.owner, world.project, foreign.id)
