"""projects モジュールの dependency 組み立て。

組み立て役：router 側・repository 側どちらのコードも import してよいので、
層の依存契約からは意図的に除外している（design.md §11）。
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
    # ProjectMemberRepository は構造的に MemberRoleReader を満たす（design.md §5-2）。
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
    """bearer トークンがあれば呼び出し元を解決し、無ければ ``None``。

    ``POST /invitations/{token}/accept`` は未ログインでも叩ける ── トークン
    自体が認可の代わりになる（design.md §6-1）。ヘッダーが*送られてはいるが*
    不正・失効している場合は、``auth.deps`` と同様に 401 になる（design.md §4-3）。
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
