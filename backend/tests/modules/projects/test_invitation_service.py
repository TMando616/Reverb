"""Unit tests for ``InvitationService.accept`` (design.md §9-1 / §9-2, tasks.md §3.8)."""

from datetime import UTC, datetime, timedelta

import pytest
from app.core.authorization import Actor, Role
from app.core.exceptions import AuthenticationError, ForbiddenError, NotFoundError
from app.core.security import hash_token
from app.modules.projects.models import Invitation
from app.modules.projects.service import InvitationService

from tests.modules.auth.fakes import FakeUserRepository
from tests.modules.auth.fakes import make_user as make_auth_user
from tests.modules.projects.fakes import (
    FakeInvitationRepository,
    FakeProjectMemberRepository,
    make_user,
)

TOKEN = "raw-invite-token"


def _service(
    invitations: FakeInvitationRepository,
    members: FakeProjectMemberRepository,
    users: FakeUserRepository | None = None,
) -> InvitationService:
    return InvitationService(invitations, members, users or FakeUserRepository([]))  # type: ignore[arg-type]


def _pending(
    *, project_id: int = 10, role: Role = Role.EDITOR, email: str | None = None, id: int = 1
) -> Invitation:
    invitation = Invitation(
        project_id=project_id,
        email=email,
        role=role.value,
        token_hash=hash_token(TOKEN),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        created_by=1,
    )
    invitation.id = id
    invitation.accepted_at = None
    invitation.accepted_user_id = None
    return invitation


async def test_unknown_token_is_404() -> None:
    svc = _service(FakeInvitationRepository(), FakeProjectMemberRepository())
    with pytest.raises(NotFoundError):
        await svc.accept(Actor(user_id=5, is_demo=False), TOKEN, display_name=None, password=None)


async def test_expired_invitation_is_404() -> None:
    invitations = FakeInvitationRepository()
    expired = _pending()
    expired.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    invitations.seed(expired)
    svc = _service(invitations, FakeProjectMemberRepository())

    with pytest.raises(NotFoundError):
        await svc.accept(Actor(user_id=5, is_demo=False), TOKEN, display_name=None, password=None)


async def test_already_accepted_invitation_is_404() -> None:
    invitations = FakeInvitationRepository()
    used = _pending()
    used.accepted_at = datetime.now(UTC)
    invitations.seed(used)
    svc = _service(invitations, FakeProjectMemberRepository())

    with pytest.raises(NotFoundError):
        await svc.accept(Actor(user_id=5, is_demo=False), TOKEN, display_name=None, password=None)


async def test_logged_in_demo_cannot_accept() -> None:
    invitations = FakeInvitationRepository()
    invitations.seed(_pending())
    svc = _service(invitations, FakeProjectMemberRepository())

    with pytest.raises(ForbiddenError):
        await svc.accept(Actor(user_id=5, is_demo=True), TOKEN, display_name=None, password=None)


async def test_logged_in_user_is_added_with_the_invitation_role() -> None:
    invitations = FakeInvitationRepository()
    invitations.seed(_pending(role=Role.REVIEWER))
    members = FakeProjectMemberRepository()
    svc = _service(invitations, members)

    result = await svc.accept(
        Actor(user_id=5, is_demo=False), TOKEN, display_name=None, password=None
    )

    assert result.project_id == 10
    assert result.role is Role.REVIEWER
    assert await members.role_of(5, 10) is Role.REVIEWER


async def test_existing_member_keeps_their_role_when_accepting_a_different_one() -> None:
    # §9-2: acceptance never overwrites an existing role — the link is not a
    # demotion path. The response reports the role actually held.
    invitations = FakeInvitationRepository()
    invitations.seed(_pending(role=Role.REVIEWER))
    members = FakeProjectMemberRepository(members=[(10, 5, Role.OWNER)], users=[make_user(id=5)])
    svc = _service(invitations, members)

    result = await svc.accept(
        Actor(user_id=5, is_demo=False), TOKEN, display_name=None, password=None
    )

    assert result.role is Role.OWNER
    assert await members.role_of(5, 10) is Role.OWNER
    assert invitations._by_id[1].accepted_at is not None


async def test_anonymous_acceptance_registers_a_user_from_the_invitation_email() -> None:
    invitations = FakeInvitationRepository()
    invitations.seed(_pending(email="new@example.com", role=Role.EDITOR))
    members = FakeProjectMemberRepository()
    users = FakeUserRepository([])
    svc = _service(invitations, members, users)

    result = await svc.accept(None, TOKEN, display_name="New Person", password="s3cret-pw")

    created = await users.get_by_email("new@example.com")
    assert created is not None
    assert created.password_hash != "s3cret-pw"  # stored as an Argon2 hash
    assert await members.role_of(created.id, 10) is Role.EDITOR
    assert result.role is Role.EDITOR


async def test_anonymous_acceptance_without_credentials_is_rejected() -> None:
    invitations = FakeInvitationRepository()
    invitations.seed(_pending(email="new@example.com"))
    svc = _service(invitations, FakeProjectMemberRepository())

    with pytest.raises(AuthenticationError):
        await svc.accept(None, TOKEN, display_name=None, password=None)


async def test_anonymous_acceptance_of_an_emailless_invite_is_rejected() -> None:
    invitations = FakeInvitationRepository()
    invitations.seed(_pending(email=None))
    svc = _service(invitations, FakeProjectMemberRepository())

    with pytest.raises(AuthenticationError):
        await svc.accept(None, TOKEN, display_name="X", password="pw12345")


async def test_anonymous_acceptance_when_email_already_registered_is_rejected() -> None:
    invitations = FakeInvitationRepository()
    invitations.seed(_pending(email="taken@example.com"))
    users = FakeUserRepository([make_auth_user(id=9, email="taken@example.com")])
    svc = _service(invitations, FakeProjectMemberRepository(), users)

    with pytest.raises(AuthenticationError):
        await svc.accept(None, TOKEN, display_name="X", password="pw12345")
