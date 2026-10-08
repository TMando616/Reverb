"""リビジョンと復元のテスト（content-pipeline C6・C7・design.md §4・§6-2・§6-3・tasks.md 4.5）。"""

import pytest
from app.core.exceptions import ForbiddenError, NotFoundError, VersionConflictError
from app.modules.contents.models import ContentStatus, RevisionKind

from tests.modules.contents.conftest import World


async def _kinds(world: World, content_id: int) -> list[tuple[int, str]]:
    rows = await world.contents.list_revisions(world.owner, world.project, content_id)
    return [(r.revision_no, r.kind) for r in rows]


async def test_create_makes_the_first_revision(world: World) -> None:
    content = await world.contents.create(world.editor, world.project, title="ネタ", body_md="メモ")

    assert await _kinds(world, content.id) == [(1, RevisionKind.CREATE)]
    first = await world.contents.get_revision(world.owner, world.project, content.id, 1)
    assert (first.title, first.body_md, first.created_by) == ("ネタ", "メモ", world.editor.user_id)


async def test_each_changing_save_appends_one_revision(world: World) -> None:
    content = await world.contents.create(world.owner, world.project, title="t", body_md="")

    await world.contents.update(world.owner, world.project, content.id, 1, body_md="一")
    await world.contents.update(world.owner, world.project, content.id, 2, title="T")

    assert await _kinds(world, content.id) == [
        (3, RevisionKind.SAVE),
        (2, RevisionKind.SAVE),
        (1, RevisionKind.CREATE),
    ]


async def test_unchanged_save_keeps_version_and_revisions(world: World) -> None:
    content = await world.contents.create(world.owner, world.project, title="t", body_md="b")

    same = await world.contents.update(
        world.owner, world.project, content.id, 1, title="t", body_md="b"
    )

    assert same.version == 1
    assert await _kinds(world, content.id) == [(1, RevisionKind.CREATE)]


async def test_conflicting_save_leaves_no_revision(world: World) -> None:
    content = await world.contents.create(world.owner, world.project, title="t", body_md="")
    await world.contents.update(world.owner, world.project, content.id, 1, body_md="先")

    with pytest.raises(VersionConflictError):
        await world.contents.update(world.owner, world.project, content.id, 1, body_md="後")

    assert len(await _kinds(world, content.id)) == 2


async def test_non_body_changes_make_no_revision(world: World) -> None:
    tag = await world.tags.create(world.owner, world.project, name="AWS")
    content = await world.contents.create(world.owner, world.project, title="t", body_md="")

    await world.contents.update(world.owner, world.project, content.id, 1, source_note_path="a.md")
    await world.contents.transition(
        world.owner, world.project, content.id, ContentStatus.ADOPTED, 2
    )
    await world.contents.set_tags(world.owner, world.project, content.id, [tag.id])

    assert await _kinds(world, content.id) == [(1, RevisionKind.CREATE)]


async def test_restore_appends_a_new_revision_with_the_old_text(world: World) -> None:
    content = await world.contents.create(world.owner, world.project, title="t", body_md="初稿")
    await world.contents.update(world.owner, world.project, content.id, 1, body_md="書き直し")

    restored = await world.contents.restore(world.editor, world.project, content.id, 1, 2)

    assert restored.body_md == "初稿"
    assert restored.version == 3
    latest = await world.contents.get_revision(world.owner, world.project, content.id, 3)
    assert (latest.kind, latest.restored_from_no, latest.body_md) == (
        RevisionKind.RESTORE,
        1,
        "初稿",
    )
    # 履歴は巻き戻さない：2版目も残っている
    assert [no for no, _ in await _kinds(world, content.id)] == [3, 2, 1]


async def test_restoring_the_current_text_does_nothing(world: World) -> None:
    content = await world.contents.create(world.owner, world.project, title="t", body_md="b")

    same = await world.contents.restore(world.owner, world.project, content.id, 1, 1)

    assert same.version == 1
    assert len(await _kinds(world, content.id)) == 1


async def test_restore_with_a_stale_version_conflicts(world: World) -> None:
    content = await world.contents.create(world.owner, world.project, title="t", body_md="初稿")
    await world.contents.update(world.owner, world.project, content.id, 1, body_md="書き直し")

    with pytest.raises(VersionConflictError):
        await world.contents.restore(world.owner, world.project, content.id, 1, 1)


async def test_missing_revision_is_not_found(world: World) -> None:
    content = await world.contents.create(world.owner, world.project, title="t", body_md="")

    with pytest.raises(NotFoundError):
        await world.contents.get_revision(world.owner, world.project, content.id, 99)
    with pytest.raises(NotFoundError):
        await world.contents.restore(world.owner, world.project, content.id, 99, 1)


async def test_revisions_of_another_project_are_not_found(world: World) -> None:
    foreign = await world.contents.create(world.owner, world.other_project, title="t", body_md="")

    # 自分がメンバーの企画の id を使っても、他企画のコンテンツの版には届かない
    with pytest.raises(NotFoundError):
        await world.contents.list_revisions(world.owner, world.project, foreign.id)
    with pytest.raises(NotFoundError):
        await world.contents.get_revision(world.owner, world.project, foreign.id, 1)


async def test_reviewer_and_demo_can_read_but_not_restore(world: World) -> None:
    content = await world.contents.create(world.owner, world.project, title="t", body_md="初稿")
    await world.contents.update(world.owner, world.project, content.id, 1, body_md="書き直し")

    for actor in (world.reviewer, world.demo):
        assert len(await world.contents.list_revisions(actor, world.project, content.id)) == 2
        assert (
            await world.contents.get_revision(actor, world.project, content.id, 1)
        ).body_md == "初稿"
        with pytest.raises(ForbiddenError):
            await world.contents.restore(actor, world.project, content.id, 1, 2)
        with pytest.raises(ForbiddenError):
            await world.contents.update(actor, world.project, content.id, 2, body_md="x")


async def test_list_pages_with_before_and_reports_length(world: World) -> None:
    content = await world.contents.create(world.owner, world.project, title="t", body_md="")
    for version, body in enumerate(["あ", "あい", "あいう"], start=1):
        await world.contents.update(world.owner, world.project, content.id, version, body_md=body)

    page = await world.contents.list_revisions(
        world.owner, world.project, content.id, before=4, limit=2
    )

    assert [(r.revision_no, r.body_length) for r in page] == [(3, 2), (2, 1)]
