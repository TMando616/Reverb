"""``ProjectRepository`` / ``ProjectMemberRepository`` のユニットテスト（design.md §13）。

Service のテストは fake を使うので、ここが実 SQL（join・ON CONFLICT・FOR UPDATE）を
確かめる唯一の場所になる。
"""

from datetime import UTC, datetime, timedelta

import pytest
from app.core.authorization import Role
from app.modules.auth.models import User
from app.modules.projects.repository import (
    InvitationRepository,
    ProjectMemberRepository,
    ProjectRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user


@pytest.fixture
async def users(db_session: AsyncSession) -> tuple[User, User]:
    owner = await create_user(db_session, "owner@example.com", display_name="オーナー")
    other = await create_user(db_session, "other@example.com", display_name="ほか")
    return owner, other


async def test_list_for_user_returns_only_projects_you_belong_to(
    db_session: AsyncSession, users: tuple[User, User]
) -> None:
    owner, other = users
    projects = ProjectRepository(db_session)
    members = ProjectMemberRepository(db_session)

    mine = await projects.create(name="自分の企画", created_by=owner.id)
    theirs = await projects.create(name="他人の企画", created_by=other.id)
    await members.add(project_id=mine.id, user_id=owner.id, role=Role.OWNER)
    await members.add(project_id=theirs.id, user_id=other.id, role=Role.OWNER)

    rows = await projects.list_for_user(owner.id)

    assert [(project.id, role) for project, role in rows] == [(mine.id, Role.OWNER)]


async def test_add_does_not_overwrite_an_existing_role(
    db_session: AsyncSession, users: tuple[User, User]
) -> None:
    # ON CONFLICT DO NOTHING（design.md §9-2）。招待の受諾で黙って降格させない。
    owner, other = users
    project = await ProjectRepository(db_session).create(name="企画", created_by=owner.id)
    members = ProjectMemberRepository(db_session)

    await members.add(project_id=project.id, user_id=other.id, role=Role.EDITOR)
    await members.add(project_id=project.id, user_id=other.id, role=Role.REVIEWER)

    assert await members.role_of(other.id, project.id) == Role.EDITOR


async def test_role_of_is_scoped_to_the_project(
    db_session: AsyncSession, users: tuple[User, User]
) -> None:
    owner, other = users
    projects = ProjectRepository(db_session)
    members = ProjectMemberRepository(db_session)
    joined = await projects.create(name="参加している", created_by=owner.id)
    separate = await projects.create(name="参加していない", created_by=owner.id)
    await members.add(project_id=joined.id, user_id=other.id, role=Role.REVIEWER)

    assert await members.role_of(other.id, joined.id) == Role.REVIEWER
    assert await members.role_of(other.id, separate.id) is None


async def test_lock_and_count_owners_counts_only_owners_of_that_project(
    db_session: AsyncSession, users: tuple[User, User]
) -> None:
    owner, other = users
    projects = ProjectRepository(db_session)
    members = ProjectMemberRepository(db_session)
    project = await projects.create(name="企画", created_by=owner.id)
    elsewhere = await projects.create(name="別企画", created_by=owner.id)
    await members.add(project_id=project.id, user_id=owner.id, role=Role.OWNER)
    await members.add(project_id=project.id, user_id=other.id, role=Role.EDITOR)
    await members.add(project_id=elsewhere.id, user_id=other.id, role=Role.OWNER)

    assert await members.lock_and_count_owners(project.id) == 1


async def test_list_members_joins_the_user_row(
    db_session: AsyncSession, users: tuple[User, User]
) -> None:
    owner, other = users
    project = await ProjectRepository(db_session).create(name="企画", created_by=owner.id)
    members = ProjectMemberRepository(db_session)
    await members.add(project_id=project.id, user_id=owner.id, role=Role.OWNER)
    await members.add(project_id=project.id, user_id=other.id, role=Role.REVIEWER)

    rows = await members.list_members(project.id)

    assert [(member.user_id, user.display_name) for member, user in rows] == [
        (owner.id, "オーナー"),
        (other.id, "ほか"),
    ]


async def test_update_role_and_remove_are_scoped(
    db_session: AsyncSession, users: tuple[User, User]
) -> None:
    owner, other = users
    projects = ProjectRepository(db_session)
    members = ProjectMemberRepository(db_session)
    project = await projects.create(name="企画", created_by=owner.id)
    elsewhere = await projects.create(name="別企画", created_by=owner.id)
    await members.add(project_id=project.id, user_id=other.id, role=Role.EDITOR)
    await members.add(project_id=elsewhere.id, user_id=other.id, role=Role.EDITOR)

    await members.update_role(project.id, other.id, Role.REVIEWER)
    assert await members.role_of(other.id, project.id) == Role.REVIEWER
    # 同じ user_id の別企画の行は巻き込まれない。
    assert await members.role_of(other.id, elsewhere.id) == Role.EDITOR

    await members.remove(project.id, other.id)
    assert await members.role_of(other.id, project.id) is None
    assert await members.role_of(other.id, elsewhere.id) == Role.EDITOR


async def test_mark_accepted_succeeds_only_once(
    db_session: AsyncSession, users: tuple[User, User]
) -> None:
    """招待は1回だけ使える。同じリンクを2人が同時に開いても2人目は負ける。"""
    owner, other = users
    project = await ProjectRepository(db_session).create(name="企画", created_by=owner.id)
    invitations = InvitationRepository(db_session)
    invitation = await invitations.create(
        project_id=project.id,
        email=None,
        role=Role.EDITOR,
        token_hash="a" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=7),
        created_by=owner.id,
    )

    first = await invitations.mark_accepted(invitation.id, accepted_user_id=owner.id)
    second = await invitations.mark_accepted(invitation.id, accepted_user_id=other.id)

    assert (first, second) == (True, False)
    # 受諾者は先に成功した方のまま（後勝ちで上書きされない）。UPDATE は SQL で
    # 走らせているので、手元のインスタンスを読み直してから確かめる。
    await db_session.refresh(invitation)
    assert invitation.accepted_user_id == owner.id


@pytest.fixture
async def pending_invitation(
    db_session: AsyncSession, users: tuple[User, User]
) -> tuple[InvitationRepository, int, str]:
    owner, _ = users
    project = await ProjectRepository(db_session).create(name="企画", created_by=owner.id)
    invitations = InvitationRepository(db_session)
    invitation = await invitations.create(
        project_id=project.id,
        email=None,
        role=Role.EDITOR,
        token_hash="b" * 64,
        expires_at=datetime.now(UTC) + timedelta(days=7),
        created_by=owner.id,
    )
    return invitations, invitation.id, invitation.token_hash


async def test_find_valid_by_token_hash_returns_a_pending_invitation(
    pending_invitation: tuple[InvitationRepository, int, str],
) -> None:
    invitations, invitation_id, token_hash = pending_invitation

    found = await invitations.find_valid_by_token_hash(token_hash)

    assert found is not None and found.id == invitation_id


async def test_find_valid_by_token_hash_hides_an_accepted_invitation(
    pending_invitation: tuple[InvitationRepository, int, str], users: tuple[User, User]
) -> None:
    # 受諾済みは「無い」。呼び出し元が 404 に倒す（design.md §6-3）。
    invitations, invitation_id, token_hash = pending_invitation
    owner, _ = users
    await invitations.mark_accepted(invitation_id, accepted_user_id=owner.id)

    assert await invitations.find_valid_by_token_hash(token_hash) is None


async def test_find_valid_by_token_hash_hides_an_expired_invitation(
    db_session: AsyncSession, users: tuple[User, User]
) -> None:
    owner, _ = users
    project = await ProjectRepository(db_session).create(name="企画", created_by=owner.id)
    invitations = InvitationRepository(db_session)
    await invitations.create(
        project_id=project.id,
        email=None,
        role=Role.EDITOR,
        token_hash="c" * 64,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        created_by=owner.id,
    )

    assert await invitations.find_valid_by_token_hash("c" * 64) is None


async def test_find_valid_by_token_hash_is_unknown_for_a_wrong_token(
    pending_invitation: tuple[InvitationRepository, int, str],
) -> None:
    invitations, _, _ = pending_invitation

    assert await invitations.find_valid_by_token_hash("d" * 64) is None
