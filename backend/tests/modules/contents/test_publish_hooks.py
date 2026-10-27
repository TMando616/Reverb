"""publishing から呼ばれる公開まわりの入口のテスト（publishing design.md §4）。

``published`` へは汎用の遷移 API からは動かせず、公開操作の中の ``mark_published`` だけが
動かす。取消で公開物が0件になったら ``mark_unpublished`` で執筆中へ戻す。
"""

import pytest
from app.core.exceptions import ForbiddenError, InvalidStateTransitionError, NotFoundError
from app.modules.contents.models import Content, ContentStatus, ContentStatusTransition
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.modules.contents.conftest import World

S = ContentStatus


async def _content(world: World, db_session: AsyncSession, status: ContentStatus) -> Content:
    content = await world.contents.create(world.owner, world.project, title="ネタ", body_md="本文")
    # 任意の状態を作るため遷移を経由せず直接置く。flush して version を確定させておく。
    content.status = status.value
    await db_session.flush()
    return content


async def _transition_count(db_session: AsyncSession, content: Content) -> int:
    return (
        await db_session.scalar(
            select(func.count()).where(ContentStatusTransition.content_id == content.id)
        )
        or 0
    )


@pytest.mark.parametrize("start", [S.DRAFTING, S.IN_REVIEW])
async def test_publishing_moves_to_published_and_logs_once(
    world: World, db_session: AsyncSession, start: ContentStatus
) -> None:
    content = await _content(world, db_session, start)

    locked = await world.contents.lock_for_publish(world.owner, world.project, content.id)
    await world.contents.mark_published(world.owner, locked)

    assert locked.status == S.PUBLISHED
    assert await _transition_count(db_session, content) == 1


async def test_publishing_again_keeps_the_state_without_a_log(
    world: World, db_session: AsyncSession
) -> None:
    content = await _content(world, db_session, S.DRAFTING)
    await world.contents.mark_published(world.owner, content)

    await world.contents.mark_published(world.owner, content)

    assert content.status == S.PUBLISHED
    assert await _transition_count(db_session, content) == 1


@pytest.mark.parametrize("start", [S.INBOX, S.ADOPTED, S.SHELVED])
async def test_cannot_publish_from_before_writing(
    world: World, db_session: AsyncSession, start: ContentStatus
) -> None:
    content = await _content(world, db_session, start)

    with pytest.raises(InvalidStateTransitionError):
        world.contents.ensure_publishable(content)
    with pytest.raises(InvalidStateTransitionError):
        await world.contents.mark_published(world.owner, content)


async def test_the_generic_transition_api_still_cannot_reach_published(
    world: World, db_session: AsyncSession
) -> None:
    content = await _content(world, db_session, S.IN_REVIEW)

    with pytest.raises(InvalidStateTransitionError):
        await world.contents.transition(
            world.owner, world.project, content.id, S.PUBLISHED, content.version
        )


async def test_unpublishing_goes_back_to_drafting_with_a_log(
    world: World, db_session: AsyncSession
) -> None:
    content = await _content(world, db_session, S.IN_REVIEW)
    await world.contents.mark_published(world.owner, content)

    await world.contents.mark_unpublished(world.owner, content)

    assert content.status == S.DRAFTING
    assert await _transition_count(db_session, content) == 2


async def test_unpublishing_a_content_that_is_not_published_does_nothing(
    world: World, db_session: AsyncSession
) -> None:
    content = await _content(world, db_session, S.DRAFTING)

    await world.contents.mark_unpublished(world.owner, content)

    assert content.status == S.DRAFTING
    assert await _transition_count(db_session, content) == 0


@pytest.mark.parametrize("who", ["editor", "reviewer", "demo"])
async def test_only_the_owner_can_lock_for_publish(
    world: World, db_session: AsyncSession, who: str
) -> None:
    content = await _content(world, db_session, S.DRAFTING)

    with pytest.raises(ForbiddenError):
        await world.contents.lock_for_publish(getattr(world, who), world.project, content.id)


async def test_locking_another_projects_content_is_not_found(
    world: World, db_session: AsyncSession
) -> None:
    content = await _content(world, db_session, S.DRAFTING)

    with pytest.raises(NotFoundError):
        await world.contents.lock_for_publish(world.owner, world.other_project, content.id)


async def test_latest_revision_number_follows_body_saves_only(
    world: World, db_session: AsyncSession
) -> None:
    content = await _content(world, db_session, S.DRAFTING)
    assert await world.contents.latest_revision_no(content) == 1

    await world.contents.update(
        world.owner, world.project, content.id, content.version, body_md="直した"
    )
    await world.contents.mark_published(world.owner, content)

    # 状態遷移では版は増えない。原稿の新旧を version でなく版番号で見る理由（§3-2）。
    assert await world.contents.latest_revision_no(content) == 2
