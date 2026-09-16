"""Dependency wiring for the contents module.

The assembly role: allowed to import both router-facing and repository-facing
code, so it is intentionally excluded from the layers contract (design.md §11).
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
        # ProjectMemberRepository satisfies MemberRoleReader structurally (design.md §5-2).
        authz=ProjectAuthorizer(ProjectMemberRepository(session)),
        transitions=ContentTransitionRepository(session),
    )
