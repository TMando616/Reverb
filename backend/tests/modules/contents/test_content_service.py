"""``ContentService`` の CRUD と楽観ロックのユニットテスト（design.md §3-3、tasks.md §5.7）。"""

import pytest
from app.core.authorization import Actor, ProjectAuthorizer, Role
from app.core.exceptions import ForbiddenError, NotFoundError, VersionConflictError
from app.modules.contents.models import Content, ContentStatus
from app.modules.contents.service import ContentService

from tests.modules.contents.fakes import FakeContentRepository, FakeContentTransitionRepository
from tests.modules.projects.fakes import FakeProjectMemberRepository

PROJECT = 10
OTHER_PROJECT = 20

OWNER = Actor(user_id=1, is_demo=False)
EDITOR = Actor(user_id=2, is_demo=False)
REVIEWER = Actor(user_id=3, is_demo=False)
DEMO_OWNER = Actor(user_id=4, is_demo=True)
OUTSIDER = Actor(user_id=5, is_demo=False)


def _setup() -> tuple[ContentService, FakeContentRepository]:
    members = FakeProjectMemberRepository(
        members=[
            (PROJECT, OWNER.user_id, Role.OWNER),
            (PROJECT, EDITOR.user_id, Role.EDITOR),
            (PROJECT, REVIEWER.user_id, Role.REVIEWER),
            # owner role であっても demo は読み取り専用に固定される（design.md §5-2）。
            (PROJECT, DEMO_OWNER.user_id, Role.OWNER),
            (OTHER_PROJECT, OWNER.user_id, Role.OWNER),
        ]
    )
    contents = FakeContentRepository()
    service = ContentService(
        contents,  # type: ignore[arg-type]
        ProjectAuthorizer(members),
        FakeContentTransitionRepository(),  # type: ignore[arg-type]
    )
    return service, contents


async def _seed(service: ContentService, *, project_id: int = PROJECT) -> Content:
    return await service.create(OWNER, project_id, title="idea", body_md="memo")


async def test_editor_creates_content_in_inbox_at_version_1() -> None:
    service, _ = _setup()

    content = await service.create(EDITOR, PROJECT, title="idea", body_md="")

    assert content.status == ContentStatus.INBOX
    assert content.version == 1
    assert content.created_by == EDITOR.user_id
    assert content.project_id == PROJECT


@pytest.mark.parametrize("actor", [REVIEWER, DEMO_OWNER], ids=["reviewer", "demo"])
async def test_reviewer_and_demo_cannot_write(actor: Actor) -> None:
    service, _ = _setup()
    content = await _seed(service)

    with pytest.raises(ForbiddenError):
        await service.create(actor, PROJECT, title="x", body_md="")
    with pytest.raises(ForbiddenError):
        await service.update(actor, PROJECT, content.id, 1, title="x")
    with pytest.raises(ForbiddenError):
        await service.delete(actor, PROJECT, content.id)


@pytest.mark.parametrize("actor", [REVIEWER, DEMO_OWNER], ids=["reviewer", "demo"])
async def test_reviewer_and_demo_can_read(actor: Actor) -> None:
    service, _ = _setup()
    content = await _seed(service)

    assert (await service.get(actor, PROJECT, content.id)).id == content.id
    assert [c.id for c in await service.list(actor, PROJECT)] == [content.id]


async def test_non_member_gets_404_not_403() -> None:
    service, _ = _setup()
    content = await _seed(service)

    with pytest.raises(NotFoundError):
        await service.get(OUTSIDER, PROJECT, content.id)
    with pytest.raises(NotFoundError):
        await service.create(OUTSIDER, PROJECT, title="x", body_md="")


async def test_content_of_another_project_is_404_even_for_a_member_of_both() -> None:
    service, _ = _setup()
    content = await _seed(service, project_id=PROJECT)

    with pytest.raises(NotFoundError):
        await service.get(OWNER, OTHER_PROJECT, content.id)
    with pytest.raises(NotFoundError):
        await service.update(OWNER, OTHER_PROJECT, content.id, 1, title="hijack")
    with pytest.raises(NotFoundError):
        await service.delete(OWNER, OTHER_PROJECT, content.id)


async def test_update_bumps_version_and_keeps_omitted_fields() -> None:
    service, _ = _setup()
    content = await _seed(service)

    updated = await service.update(EDITOR, PROJECT, content.id, 1, body_md="edited")

    assert updated.version == 2
    assert (updated.title, updated.body_md) == ("idea", "edited")


async def test_stale_expected_version_is_409_and_changes_nothing() -> None:
    service, _ = _setup()
    content = await _seed(service)
    await service.update(OWNER, PROJECT, content.id, 1, title="first")

    with pytest.raises(VersionConflictError):
        await service.update(EDITOR, PROJECT, content.id, 1, title="second")

    current = await service.get(OWNER, PROJECT, content.id)
    assert (current.title, current.version) == ("first", 2)


async def test_conflict_detected_at_flush_is_409() -> None:
    # 2段目：version は読み込み時点では一致していたが、flush より前に別の
    # 書き手が入ってきたケース。
    service, contents = _setup()
    content = await _seed(service)
    contents.lose_next_race()

    with pytest.raises(VersionConflictError):
        await service.update(EDITOR, PROJECT, content.id, 1, title="late")


async def test_unchanged_patch_keeps_version_without_breaking_conflict_detection() -> None:
    """design.md §3-3：変更のない PATCH は UPDATE を発行しないので ``version`` は
    そのまま。だからといって穴を開けてはいけない：古い version を持つクライアント
    が成功するのは実際に何も変わっていない間だけで、何かが変わった瞬間に 409 になる。
    """
    service, _ = _setup()
    content = await _seed(service)

    same = await service.update(EDITOR, PROJECT, content.id, 1, title="idea", body_md="memo")
    assert same.version == 1

    # version 1 を持つ別のクライアント：まだ有効。見ているデータは最新のまま。
    changed = await service.update(OWNER, PROJECT, content.id, 1, title="renamed")
    assert changed.version == 2

    # 最初のクライアントは version 1 のまま ── ここで初めて本当に古くなる。
    with pytest.raises(VersionConflictError):
        await service.update(EDITOR, PROJECT, content.id, 1, body_md="overwrite")


async def test_deleted_content_disappears_from_list_and_get() -> None:
    service, _ = _setup()
    kept = await _seed(service)
    gone = await _seed(service)

    await service.delete(EDITOR, PROJECT, gone.id)

    assert [c.id for c in await service.list(OWNER, PROJECT)] == [kept.id]
    with pytest.raises(NotFoundError):
        await service.get(OWNER, PROJECT, gone.id)
    with pytest.raises(NotFoundError):
        await service.delete(OWNER, PROJECT, gone.id)


async def test_list_filters_by_a_single_status() -> None:
    service, _ = _setup()
    inbox = await _seed(service)
    adopted = await _seed(service)
    adopted.status = ContentStatus.ADOPTED.value

    assert [c.id for c in await service.list(OWNER, PROJECT, status=ContentStatus.INBOX)] == [
        inbox.id
    ]
    assert [c.id for c in await service.list(OWNER, PROJECT, status=ContentStatus.ADOPTED)] == [
        adopted.id
    ]
