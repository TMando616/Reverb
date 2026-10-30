"""publishing モジュールの DB アクセス（publishing design.md §3）。

業務ルールは持たない（ADR-0009）。コンテンツに属する行は ``content_id`` で絞る。
コンテンツが企画に属しているかは、Service が先に ``ContentGateway`` で確かめる。
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from app.channels.capabilities import ChannelCode
from app.core.exceptions import ConversionInProgressError, VersionConflictError
from app.modules.contents.models import Content
from app.modules.publishing.models import (
    ChannelAccount,
    ChannelDraft,
    ConversionJob,
    ConversionProfile,
    JobStatus,
    Publication,
)
from app.modules.publishing.ports import ProfileSnapshot


async def _flush_mapping_conflicts(session: AsyncSession) -> None:
    """flush し、楽観ロックの競合負けを 409 にする（contents の同名関数と同じ）。"""
    try:
        await session.flush()
    except StaleDataError as exc:
        raise VersionConflictError() from exc


class ChannelAccountRepository:
    """ユーザー×チャネルのトークン。読み書きは常に ``user_id`` で絞る（design.md §5）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int, channel: ChannelCode) -> ChannelAccount | None:
        result = await self._session.execute(
            select(ChannelAccount).where(
                ChannelAccount.user_id == user_id, ChannelAccount.channel == channel.value
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self, *, user_id: int, channel: ChannelCode, encrypted_token: bytes, external_user_id: str
    ) -> ChannelAccount:
        """登録と差し替えを1文で。同じ人が2タブで同時に登録しても UNIQUE で落ちない。"""
        values = insert(ChannelAccount).values(
            user_id=user_id,
            channel=channel.value,
            encrypted_token=encrypted_token,
            external_user_id=external_user_id,
        )
        stmt = values.on_conflict_do_update(
            constraint="uq_channel_accounts_user_channel",
            set_={
                "encrypted_token": values.excluded.encrypted_token,
                "external_user_id": values.excluded.external_user_id,
                "updated_at": func.now(),
            },
        ).returning(ChannelAccount)
        # 同じセッションに古い行が載っていても、返ってきた値で上書きする。
        result = await self._session.scalars(stmt, execution_options={"populate_existing": True})
        return result.one()

    async def replace_token(self, account: ChannelAccount, encrypted_token: bytes) -> None:
        """古い鍵の暗号文を先頭の鍵で暗号化し直す（design.md §10-1）。"""
        account.encrypted_token = encrypted_token
        await self._session.flush()

    async def delete(self, user_id: int, channel: ChannelCode) -> None:
        await self._session.execute(
            delete(ChannelAccount).where(
                ChannelAccount.user_id == user_id, ChannelAccount.channel == channel.value
            )
        )


class ConversionProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(
        self, project_id: int, channel: ChannelCode, default: ProfileSnapshot
    ) -> ConversionProfile:
        """初めて変換するときに既定値から行を作る（design.md §3-2）。

        同時に2つ来ても UNIQUE と衝突しないよう ``ON CONFLICT DO NOTHING`` で入れてから読む。
        """
        await self._session.execute(
            insert(ConversionProfile)
            .values(
                project_id=project_id,
                channel=channel.value,
                structure=default.structure,
                tone=default.tone,
                first_person=default.first_person,
                banned_phrases=default.banned_phrases,
                version=1,
            )
            .on_conflict_do_nothing(constraint="uq_conversion_profiles_project_channel")
        )
        result = await self._session.scalars(
            select(ConversionProfile).where(
                ConversionProfile.project_id == project_id,
                ConversionProfile.channel == channel.value,
            )
        )
        return result.one()


class ConversionJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: int,
        content_id: int,
        channel: ChannelCode,
        requested_by: int,
        source_revision_no: int,
        profile_snapshot: dict[str, Any],
        model: str,
    ) -> ConversionJob:
        job = ConversionJob(
            project_id=project_id,
            content_id=content_id,
            channel=channel.value,
            status=JobStatus.QUEUED.value,
            requested_by=requested_by,
            source_revision_no=source_revision_no,
            profile_snapshot=profile_snapshot,
            model=model,
        )
        try:
            # 部分 UNIQUE に当たってもトランザクション全体を壊さないよう SAVEPOINT の中で。
            async with self._session.begin_nested():
                self._session.add(job)
                await self._session.flush()
        except IntegrityError as exc:
            if "uq_conversion_jobs_active" in str(exc.orig):
                raise ConversionInProgressError() from exc
            raise
        return job

    async def get(self, job_id: int) -> ConversionJob | None:
        return await self._session.get(ConversionJob, job_id)

    async def get_for_content(self, job_id: int, content_id: int) -> ConversionJob | None:
        result = await self._session.scalars(
            select(ConversionJob).where(
                ConversionJob.id == job_id, ConversionJob.content_id == content_id
            )
        )
        return result.one_or_none()

    async def list_for_content(self, content_id: int, limit: int = 50) -> Sequence[ConversionJob]:
        result = await self._session.scalars(
            select(ConversionJob)
            .where(ConversionJob.content_id == content_id)
            .order_by(ConversionJob.id.desc())
            .limit(limit)
        )
        return result.all()

    async def latest_for(self, content_id: int, channel: ChannelCode) -> ConversionJob | None:
        result = await self._session.scalars(
            select(ConversionJob)
            .where(ConversionJob.content_id == content_id, ConversionJob.channel == channel.value)
            .order_by(ConversionJob.id.desc())
            .limit(1)
        )
        return result.one_or_none()

    async def claim_next(self, now: datetime) -> ConversionJob | None:
        """待機中で一番古い1件を ``running`` にして返す（ADR-0017）。

        ``FOR UPDATE SKIP LOCKED``：別のワーカーが押さえている行は飛ばすので、
        ワーカーが複数動いても同じ行を2つが拾わない。
        """
        result = await self._session.scalars(
            select(ConversionJob)
            .where(ConversionJob.status == JobStatus.QUEUED.value)
            .order_by(ConversionJob.created_at, ConversionJob.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = result.one_or_none()
        if job is None:
            return None
        job.status = JobStatus.RUNNING.value
        job.started_at = now
        await self._session.flush()
        return job

    async def reap_stuck(self, started_before: datetime, now: datetime) -> int:
        """``running`` のまま止まった行を ``interrupted`` で失敗にする（design.md §7-3）。"""
        result = await self._session.execute(
            update(ConversionJob)
            .where(
                ConversionJob.status == JobStatus.RUNNING.value,
                ConversionJob.started_at < started_before,
            )
            .values(
                status=JobStatus.FAILED.value,
                finished_at=now,
                error_code="interrupted",
                error_message="the worker stopped before finishing",
                updated_at=func.now(),
            )
            .returning(ConversionJob.id)
        )
        return len(result.all())

    async def flush(self) -> None:
        await self._session.flush()


class ChannelDraftRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, content_id: int, channel: ChannelCode) -> ChannelDraft | None:
        result = await self._session.scalars(
            select(ChannelDraft).where(
                ChannelDraft.content_id == content_id, ChannelDraft.channel == channel.value
            )
        )
        return result.one_or_none()

    async def create(
        self,
        *,
        project_id: int,
        content_id: int,
        channel: ChannelCode,
        title: str,
        body: str,
        extra: dict[str, Any],
        source_revision_no: int,
        applied_job_id: int,
    ) -> ChannelDraft:
        draft = ChannelDraft(
            project_id=project_id,
            content_id=content_id,
            channel=channel.value,
            title=title,
            body=body,
            extra=extra,
            source_revision_no=source_revision_no,
            applied_job_id=applied_job_id,
            edited_after_apply=False,
        )
        self._session.add(draft)
        await self.flush()
        return draft

    async def flush(self) -> None:
        """保留中の変更を flush する（楽観ロックの競合は 409）。"""
        await _flush_mapping_conflicts(self._session)


class PublicationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        project_id: int,
        content_id: int,
        channel: ChannelCode,
        external_id: str,
        url: str,
        visibility: str | None,
        published_by: int,
    ) -> Publication:
        publication = Publication(
            project_id=project_id,
            content_id=content_id,
            channel=channel.value,
            external_id=external_id,
            url=url,
            visibility=visibility,
            published_by=published_by,
        )
        self._session.add(publication)
        await self._session.flush()
        return publication

    async def get_in_project(self, publication_id: int, project_id: int) -> Publication | None:
        result = await self._session.scalars(
            select(Publication).where(
                Publication.id == publication_id, Publication.project_id == project_id
            )
        )
        return result.one_or_none()

    async def count_active(self, content_id: int) -> int:
        return (
            await self._session.scalar(
                select(func.count()).where(
                    Publication.content_id == content_id, Publication.cancelled_at.is_(None)
                )
            )
            or 0
        )

    async def list_active_in_project(
        self, project_id: int, *, content_id: int | None = None
    ) -> Sequence[tuple[Publication, str]]:
        """企画の取り消されていない公開物と、そのコンテンツのタイトル（新しい順）。"""
        stmt = (
            select(Publication, Content.title)
            .join(Content, Content.id == Publication.content_id)
            .where(
                Publication.project_id == project_id,
                Publication.cancelled_at.is_(None),
                Content.deleted_at.is_(None),
            )
        )
        if content_id is not None:
            stmt = stmt.where(Publication.content_id == content_id)
        result = await self._session.execute(
            stmt.order_by(Publication.published_at.desc(), Publication.id.desc())
        )
        return [(row[0], row[1]) for row in result.tuples()]

    async def reload(self, publication: Publication) -> None:
        """DB の今の値で読み直す（ロックを取ったあとの再確認用）。"""
        await self._session.refresh(publication)

    async def flush(self) -> None:
        await self._session.flush()

    async def get_active(self, content_id: int, channel: ChannelCode) -> Publication | None:
        """取り消されていない公開物（コンテンツ×チャネルで高々1件・部分 UNIQUE）。"""
        result = await self._session.scalars(
            select(Publication).where(
                Publication.content_id == content_id,
                Publication.channel == channel.value,
                Publication.cancelled_at.is_(None),
            )
        )
        return result.one_or_none()
