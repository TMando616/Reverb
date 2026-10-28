"""publishing モジュールの Pydantic リクエスト/レスポンススキーマ。"""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StringConstraints

from app.channels.capabilities import ChannelCode
from app.modules.contents.schemas import BODY_MD_MAX_LENGTH
from app.modules.publishing.models import ChannelDraft, ConversionJob, JobStatus, Visibility
from app.modules.publishing.service import ChannelView


class QiitaAccountOut(BaseModel):
    """登録状況だけを返す。**トークンは返さない**（C5）。"""

    registered: bool
    external_user_id: str | None = None


class QiitaAccountRegisterRequest(BaseModel):
    # SecretStr にしておくと、repr・ログ・検証エラーに値が出ない。
    token: Annotated[SecretStr, StringConstraints(min_length=1, max_length=200)]


class ChannelOut(BaseModel):
    """チャネルと capabilities。画面はこれを見てボタンを出し分ける（C1）。"""

    code: ChannelCode
    label: str
    publish: str
    metrics: str
    format: str
    max_length: int | None


class ConversionJobSummary(BaseModel):
    """変換の履歴の1行（結果の本文は含めない）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: ChannelCode
    status: JobStatus
    requested_by: int
    source_revision_no: int
    model: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None


class ConversionJobOut(ConversionJobSummary):
    result_title: str | None
    result_body: str | None
    result_tags: list[str]
    # 変換したときのプロファイル（C2「過去の変換が何で作られたか分かる」）。
    profile_snapshot: dict[str, Any]
    input_tokens: int | None
    output_tokens: int | None

    @classmethod
    def from_job(cls, job: ConversionJob) -> "ConversionJobOut":
        extra = job.result_extra or {}
        return cls.model_validate(
            {
                **ConversionJobSummary.model_validate(job).model_dump(),
                "result_title": job.result_title,
                "result_body": job.result_body,
                "result_tags": [str(t) for t in extra.get("tags", [])],
                "profile_snapshot": job.profile_snapshot,
                "input_tokens": job.input_tokens,
                "output_tokens": job.output_tokens,
            }
        )


# 原稿で持てるタグの数。Qiita の制約（1〜5個）は投稿時に見る（design.md §10-4）。
# 保存では編集途中を許し、リクエストの巨大化だけを止める。
_DRAFT_TAGS_MAX_ITEMS = 10

DraftTag = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class DraftSaveRequest(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    body: Annotated[str, StringConstraints(max_length=BODY_MD_MAX_LENGTH)]
    tags: Annotated[list[DraftTag], Field(max_length=_DRAFT_TAGS_MAX_ITEMS)] = []
    expected_version: int


class DraftApplyRequest(BaseModel):
    job_id: int
    expected_version: int


class ChannelDraftOut(BaseModel):
    id: int
    title: str
    body: str
    tags: list[str]
    version: int
    source_revision_no: int
    applied_job_id: int | None
    edited_after_apply: bool
    pending_job_id: int | None
    updated_at: datetime

    @classmethod
    def from_draft(cls, draft: ChannelDraft) -> "ChannelDraftOut":
        return cls(
            id=draft.id,
            title=draft.title,
            body=draft.body,
            tags=[str(t) for t in draft.extra.get("tags", [])],
            version=draft.version,
            source_revision_no=draft.source_revision_no,
            applied_job_id=draft.applied_job_id,
            edited_after_apply=draft.edited_after_apply,
            pending_job_id=draft.pending_job_id,
            updated_at=draft.updated_at,
        )


class PublicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content_id: int
    channel: ChannelCode
    external_id: str
    url: str
    visibility: Visibility | None
    published_at: datetime
    published_by: int
    last_pushed_at: datetime | None


class ChannelViewOut(BaseModel):
    """公開画面の1回分（design.md §6）。"""

    channel: ChannelCode
    draft: ChannelDraftOut | None
    draft_is_stale: bool
    latest_job: ConversionJobOut | None
    pending_job: ConversionJobOut | None
    publication: PublicationOut | None
    latest_revision_no: int

    @classmethod
    def from_view(cls, view: ChannelView) -> "ChannelViewOut":
        return cls(
            channel=view.channel,
            draft=ChannelDraftOut.from_draft(view.draft) if view.draft else None,
            draft_is_stale=view.draft_is_stale,
            latest_job=ConversionJobOut.from_job(view.latest_job) if view.latest_job else None,
            pending_job=ConversionJobOut.from_job(view.pending_job) if view.pending_job else None,
            publication=PublicationOut.model_validate(view.publication)
            if view.publication
            else None,
            latest_revision_no=view.latest_revision_no,
        )
