"""Unit tests for ``MemberService`` (design.md §9-1 / §9-3, tasks.md §3.8)."""

from datetime import UTC, datetime, timedelta

import pytest
from app.core.authorization import Actor, ProjectAuthorizer, Role
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import hash_token
from app.modules.projects.service import INVITATION_TTL, MemberService

from tests.modules.projects.fakes import (
    FakeInvitationRepository,
    FakeProjectMemberRepository,
    make_user,
)

OWNER = Actor(user_id=1, is_demo=False)
EDITOR = Actor(user_id=2, is_demo=False)


def _service(members: FakeProjectMemberRepository) -> MemberService:
    return MemberService(members, FakeInvitationRepository(), ProjectAuthorizer(members))  # type: ignore[arg-type]


def _members(*rows: tuple[int, int, Role]) -> FakeProjectMemberRepository:
    users = [make_user(id=uid) for _, uid, _ in rows]
    return FakeProjectMemberRepository(members=list(rows), users=users)


async def test_non_owner_cannot_invite() -> None:
    svc = _service(_members((10, 1, Role.OWNER), (10, 2, Role.EDITOR)))
    with pytest.raises(ForbiddenError):
        await svc.invite(EDITOR, 10, role=Role.REVIEWER, email=None)


async def test_non_owner_cannot_change_role() -> None:
    svc = _service(_members((10, 1, Role.OWNER), (10, 2, Role.EDITOR)))
    with pytest.raises(ForbiddenError):
        await svc.change_role(EDITOR, 10, 1, role=Role.REVIEWER)


async def test_non_owner_cannot_remove() -> None:
    svc = _service(_members((10, 1, Role.OWNER), (10, 2, Role.EDITOR)))
    with pytest.raises(ForbiddenError):
        await svc.remove(EDITOR, 10, 1)


async def test_invite_stores_only_the_token_hash_and_returns_the_path() -> None:
    members = _members((10, 1, Role.OWNER))
    invitations = FakeInvitationRepository()
    svc = MemberService(members, invitations, ProjectAuthorizer(members))  # type: ignore[arg-type]

    before = datetime.now(UTC)
    created = await svc.invite(OWNER, 10, role=Role.REVIEWER, email="x@example.com")

    raw_token = created.accept_path.removeprefix("/invite/")
    assert created.accept_path.startswith("/invite/")
    assert created.invitation.token_hash == hash_token(raw_token)
    assert created.invitation.token_hash != raw_token
    assert INVITATION_TTL == timedelta(days=7)  # noqa: SIM300
    assert abs((created.invitation.expires_at - (before + INVITATION_TTL)).total_seconds()) < 5


async def test_demoting_the_last_owner_is_forbidden() -> None:
    svc = _service(_members((10, 1, Role.OWNER)))
    with pytest.raises(ForbiddenError):
        await svc.change_role(OWNER, 10, 1, role=Role.REVIEWER)


async def test_removing_the_last_owner_is_forbidden() -> None:
    svc = _service(_members((10, 1, Role.OWNER)))
    with pytest.raises(ForbiddenError):
        await svc.remove(OWNER, 10, 1)


async def test_demoting_an_owner_is_allowed_while_another_owner_remains() -> None:
    members = _members((10, 1, Role.OWNER), (10, 2, Role.OWNER))
    svc = _service(members)

    member = await svc.change_role(OWNER, 10, 2, role=Role.EDITOR)

    assert member.role == Role.EDITOR.value
    assert await members.role_of(2, 10) is Role.EDITOR


async def test_change_role_of_a_non_member_is_404() -> None:
    svc = _service(_members((10, 1, Role.OWNER)))
    with pytest.raises(NotFoundError):
        await svc.change_role(OWNER, 10, 999, role=Role.EDITOR)


async def test_list_members_returns_a_view_per_row() -> None:
    members = _members((10, 1, Role.OWNER), (10, 2, Role.EDITOR))
    svc = _service(members)

    views = await svc.list_members(OWNER, 10)

    assert {(v.user_id, v.role) for v in views} == {(1, Role.OWNER), (2, Role.EDITOR)}
    assert all(v.email and v.display_name for v in views)
