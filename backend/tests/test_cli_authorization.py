"""CLI 経路でも Service と同じ認可が働くこと（requirements.md F5）。

F5 の受け入れ条件「同じ Service を HTTP 以外（MCP / ジョブ）から呼んでも、
同一の認可ロジックが通る」を、いま存在する唯一の非 HTTP 経路である bootstrap CLI
で確かめる。CLI に認可の近道を作らない（design.md §9-0）ことの回帰テスト。
"""

from datetime import UTC, datetime, timedelta

import pytest
from app.cli import _accept_invitation
from app.core.authorization import Role
from app.core.exceptions import ForbiddenError
from app.core.security import hash_token
from app.modules.projects.repository import InvitationRepository, ProjectRepository
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user

TOKEN = "cli-invitation-token"


async def _invitation_for(db_session: AsyncSession, *, created_by: int) -> int:
    project = await ProjectRepository(db_session).create(name="企画", created_by=created_by)
    await InvitationRepository(db_session).create(
        project_id=project.id,
        email=None,
        role=Role.EDITOR,
        token_hash=hash_token(TOKEN),
        expires_at=datetime.now(UTC) + timedelta(days=7),
        created_by=created_by,
    )
    return project.id


async def test_cli_cannot_bypass_the_demo_guard(db_session: AsyncSession) -> None:
    owner = await create_user(db_session, "cli-owner@example.com")
    demo = await create_user(db_session, "cli-demo@example.com", is_demo=True)
    await _invitation_for(db_session, created_by=owner.id)

    # ブラウザ経由なら 403 になる操作は、CLI からでも 403 のまま。
    with pytest.raises(ForbiddenError):
        await _accept_invitation(db_session, token=TOKEN, email=demo.email)


async def test_cli_accepts_for_a_regular_user(db_session: AsyncSession) -> None:
    # 「常に失敗する」で上のテストが通ってしまわないための対。
    owner = await create_user(db_session, "cli-owner2@example.com")
    joiner = await create_user(db_session, "cli-joiner@example.com")
    project_id = await _invitation_for(db_session, created_by=owner.id)

    lines = await _accept_invitation(db_session, token=TOKEN, email=joiner.email)

    assert f"joined project #{project_id}" in lines[0]
