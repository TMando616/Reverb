"""publishing モジュールの Pydantic リクエスト/レスポンススキーマ。"""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, SecretStr, StringConstraints

from app.channels.capabilities import ChannelCode
from app.modules.publishing.models import ConversionJob, JobStatus


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
