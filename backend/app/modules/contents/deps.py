"""contents モジュールの dependency 組み立て。

組み立て役：router 側・repository 側どちらのコードも import してよいので、
層の依存契約からは意図的に除外している（design.md §11）。
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import ProjectAuthorizer
from app.core.db import get_session
from app.modules.contents.repository import ContentRepository, ContentTransitionRepository
from app.modules.contents.service import ContentService
from app.modules.projects.repository import ProjectMemberRepository

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_content_service(session: SessionDep) -> ContentService:
    return ContentService(
        contents=ContentRepository(session),
        # ProjectMemberRepository は構造的に MemberRoleReader を満たす（design.md §5-2）。
        authz=ProjectAuthorizer(ProjectMemberRepository(session)),
        transitions=ContentTransitionRepository(session),
    )
