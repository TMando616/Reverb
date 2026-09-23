"""``ContentService.transition`` のユニットテスト（design.md §8、tasks.md §6.4）。"""

import pytest
from app.core.authorization import Actor, ProjectAuthorizer, Role
from app.core.exceptions import (
    ForbiddenError,
    InvalidStateTransitionError,
    NotFoundError,
    VersionConflictError,
)
from app.modules.contents.models import Content, ContentStatus
from app.modules.contents.service import ALLOWED, ContentService

from tests.modules.contents.fakes import FakeContentRepository, FakeContentTransitionRepository
from tests.modules.projects.fakes import FakeProjectMemberRepository

PROJECT = 10
OTHER_PROJECT = 20

OWNER = Actor(user_id=1, is_demo=False)
EDITOR = Actor(user_id=2, is_demo=False)
REVIEWER = Actor(user_id=3, is_demo=False)
DEMO_OWNER = Actor(user_id=4, is_demo=True)

S = ContentStatus

# design.md §8-1 の確定表を、そのまま (from, to) の組で書き写したもの。
# ALLOWED と独立に書いておき、表の書き間違いをテストで拾う。
EXPECTED_ALLOWED = {
    (S.INBOX, S.ADOPTED),
    (S.INBOX, S.SHELVED),
    (S.ADOPTED, S.INBOX),
    (S.ADOPTED, S.DRAFTING),
    (S.ADOPTED, S.SHELVED),
    (S.DRAFTING, S.ADOPTED),
    (S.DRAFTING, S.IN_REVIEW),
    (S.DRAFTING, S.SHELVED),
    (S.IN_REVIEW, S.DRAFTING),
    (S.IN_REVIEW, S.SHELVED),
    (S.SHELVED, S.INBOX),
}


def _setup() -> tuple[ContentService, FakeContentRepository, FakeContentTransitionRepository]:
    members = FakeProjectMemberRepository(
        members=[
            (PROJECT, OWNER.user_id, Role.OWNER),
            (PROJECT, EDITOR.user_id, Role.EDITOR),
            (PROJECT, REVIEWER.user_id, Role.REVIEWER),
            (PROJECT, DEMO_OWNER.user_id, Role.OWNER),
            (OTHER_PROJECT, OWNER.user_id, Role.OWNER),
        ]
    )
    contents = FakeContentRepository()
    transitions = FakeContentTransitionRepository()
    service = ContentService(
        contents,  # type: ignore[arg-type]
        ProjectAuthorizer(members),
        transitions,  # type: ignore[arg-type]
    )
    return service, contents, transitions


async def _seed(service: ContentService, status: ContentStatus = S.INBOX) -> Content:
    content = await service.create(OWNER, PROJECT, title="idea", body_md="memo")
    # 任意の from を作るため、遷移を経由せず直接置く。422 は flush の前に出るので、
    # フェイクの version（1）はこの書き換えの影響を受けない。
    content.status = status.value
    return content


def test_allowed_matches_the_confirmed_table() -> None:
    actual = {(src, dst) for src, dsts in ALLOWED.items() for dst in dsts}
    assert actual == EXPECTED_ALLOWED
    assert set(ALLOWED) == set(ContentStatus)


@pytest.mark.parametrize(
    ("src", "dst"),
    sorted(
        (src, dst)
        for src in ContentStatus
        for dst in ContentStatus
        if src != dst and (src, dst) not in EXPECTED_ALLOWED
    ),
)
async def test_disallowed_transition_is_422_and_changes_nothing(
    src: ContentStatus, dst: ContentStatus
) -> None:
    service, _, transitions = _setup()
    content = await _seed(service, src)

    with pytest.raises(InvalidStateTransitionError):
        await service.transition(EDITOR, PROJECT, content.id, dst, 1)

    assert content.status == src.value
    assert transitions.rows == []


async def test_inbox_to_published_is_422() -> None:
    # F7 の代表例。in_review → published も publishing スペックまでは 422（上の網羅に含まれる）。
    service, _, _ = _setup()
    content = await _seed(service)

    with pytest.raises(InvalidStateTransitionError):
        await service.transition(EDITOR, PROJECT, content.id, S.PUBLISHED, 1)


async def test_allowed_transition_bumps_version_and_appends_one_log_row() -> None:
    service, _, transitions = _setup()
    content = await _seed(service)

    moved = await service.transition(EDITOR, PROJECT, content.id, S.ADOPTED, 1)

    assert moved.status == S.ADOPTED
    assert moved.version == 2
    assert len(transitions.rows) == 1
    row = transitions.rows[0]
    assert (row.content_id, row.from_status, row.to_status, row.actor_user_id) == (
        content.id,
        S.INBOX,
        S.ADOPTED,
        EDITOR.user_id,
    )


async def test_main_path_inbox_adopted_drafting() -> None:
    service, _, transitions = _setup()
    content = await _seed(service)

    await service.transition(EDITOR, PROJECT, content.id, S.ADOPTED, 1)
    moved = await service.transition(OWNER, PROJECT, content.id, S.DRAFTING, 2)

    assert (moved.status, moved.version) == (S.DRAFTING, 3)
    assert [(r.from_status, r.to_status) for r in transitions.rows] == [
        (S.INBOX, S.ADOPTED),
        (S.ADOPTED, S.DRAFTING),
    ]


@pytest.mark.parametrize("actor", [REVIEWER, DEMO_OWNER], ids=["reviewer", "demo"])
async def test_reviewer_and_demo_cannot_transition(actor: Actor) -> None:
    service, _, transitions = _setup()
    content = await _seed(service)

    with pytest.raises(ForbiddenError):
        await service.transition(actor, PROJECT, content.id, S.ADOPTED, 1)

    assert content.status == S.INBOX
    assert transitions.rows == []


async def test_content_of_another_project_is_404() -> None:
    service, _, _ = _setup()
    content = await _seed(service)

    with pytest.raises(NotFoundError):
        await service.transition(OWNER, OTHER_PROJECT, content.id, S.ADOPTED, 1)


async def test_second_of_two_concurrent_transitions_is_409() -> None:
    # 2つのクライアントが同じ version 1 を見て、それぞれ遷移を送ったケース。
    service, _, transitions = _setup()
    content = await _seed(service)

    await service.transition(OWNER, PROJECT, content.id, S.ADOPTED, 1)
    with pytest.raises(VersionConflictError):
        await service.transition(EDITOR, PROJECT, content.id, S.SHELVED, 1)

    assert (content.status, content.version) == (S.ADOPTED, 2)
    assert len(transitions.rows) == 1


async def test_conflict_detected_at_flush_is_409_without_log_row() -> None:
    # 2段目：読み込み時点の version は一致していたが、flush より前に別の遷移が
    # 入ってきたケース。遷移ログは flush の後に書くので残らない。
    service, contents, transitions = _setup()
    content = await _seed(service)
    contents.lose_next_race()

    with pytest.raises(VersionConflictError):
        await service.transition(EDITOR, PROJECT, content.id, S.ADOPTED, 1)

    assert transitions.rows == []
