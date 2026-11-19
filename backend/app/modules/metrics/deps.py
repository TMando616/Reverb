"""metrics モジュールの dependency 組み立て（metrics design.md §2）。

ポートに具体実装を差し込むのはここだけ。テストは ``app.dependency_overrides`` で差し替える。
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import ProjectAuthorizer
from app.core.db import get_session
from app.modules.metrics.repository import JobRepository, SnapshotRepository
from app.modules.metrics.service import JobService, SnapshotService
from app.modules.projects.repository import ProjectMemberRepository
from app.modules.publishing.repository import PublicationRepository

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def build_snapshot_service(session: AsyncSession) -> SnapshotService:
    """HTTP（Depends）とワーカーの両方から使う組み立て。ワーカーは自分のセッションを渡す。"""
    return SnapshotService(
        snapshots=SnapshotRepository(session),
        # 公開物の読み取りは publishing の Repository が PublicationGateway を満たす
        publications=PublicationRepository(session),
        authz=ProjectAuthorizer(ProjectMemberRepository(session)),
    )


def get_snapshot_service(session: SessionDep) -> SnapshotService:
    return build_snapshot_service(session)


def build_job_service(session: AsyncSession) -> JobService:
    return JobService(
        jobs=JobRepository(session),
        authz=ProjectAuthorizer(ProjectMemberRepository(session)),
    )


def get_job_service(session: SessionDep) -> JobService:
    return build_job_service(session)
