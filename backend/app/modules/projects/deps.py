"""Dependency wiring for the projects module.

The assembly role: allowed to import both router-facing and repository-facing
code, so it is intentionally excluded from the layers contract (design.md §11).
"""

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import Actor, ProjectAuthorizer
from app.core.db import get_session
from app.core.exceptions import AuthenticationError
from app.core.security import hash_token
from app.modules.auth.repository import SessionRepository, UserRepository
from app.modules.projects.repository import (
    InvitationRepository,
    ProjectMemberRepository,
    ProjectRepository,
)
from app.modules.projects.service import InvitationService, MemberService, ProjectService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _authorizer(session: AsyncSession) -> ProjectAuthorizer:
    # ProjectMemberRepository satisfies MemberRoleReader structurally (design.md §5-2).
    return ProjectAuthorizer(ProjectMemberRepository(session))


def get_project_service(session: SessionDep) -> ProjectService:
    return ProjectService(
        ProjectRepository(session),
        ProjectMemberRepository(session),
        _authorizer(session),
    )


def get_member_service(session: SessionDep) -> MemberService:
    return MemberService(
        ProjectMemberRepository(session),
        InvitationRepository(session),
        _authorizer(session),
    )


def get_invitation_service(session: SessionDep) -> InvitationService:
    return InvitationService(
        InvitationRepository(session),
        ProjectMemberRepository(session),
        UserRepository(session),
    )


async def get_optional_actor(
    session: SessionDep,
    authorization: Annotated[str | None, Header()] = None,
) -> Actor | None:
    """Resolve the caller if a bearer token is present, else ``None``.

    ``POST /invitations/{token}/accept`` is reachable while signed out — the
    token is the authorization (design.md §6-1). A header that *is* sent but
    malformed / stale is still a 401, matching ``auth.deps`` (design.md §4-3).
    """
    if authorization is None:
        return None
    scheme, _, raw = authorization.partition(" ")
    token = raw.strip()
    if scheme.lower() != "bearer" or not token:
        raise AuthenticationError("malformed Authorization header")
    row = await SessionRepository(session).find_valid_with_user(hash_token(token))
    if row is None:
        raise AuthenticationError()
    return Actor(user_id=row.user.id, is_demo=row.user.is_demo)


OptionalActor = Annotated[Actor | None, Depends(get_optional_actor)]
