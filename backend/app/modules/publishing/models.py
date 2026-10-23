"""publishing モジュールの ORM モデル（publishing design.md §3）。

チャネルは ``text`` ＋ CHECK 制約で持ち、定義そのものは ``app.channels.capabilities`` に置く。
コンテンツを参照する3テーブルは ``(content_id, project_id)`` の複合 FK で、企画をまたぐ
参照を DB で止める（content-pipeline design.md §3-3 と同じ）。
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.channels.capabilities import CHANNEL_CHECK_VALUES
from app.core.db import Base, TimestampMixin


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Visibility(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"  # Qiita の限定共有


_JOB_STATUS_CHECK = "status IN ({})".format(", ".join(f"'{s.value}'" for s in JobStatus))
_VISIBILITY_CHECK = "visibility IS NULL OR visibility IN ({})".format(
    ", ".join(f"'{v.value}'" for v in Visibility)
)


def _channel_check(table: str) -> CheckConstraint:
    return CheckConstraint(f"channel IN ({CHANNEL_CHECK_VALUES})", name=f"ck_{table}_channel")


def _content_fk(table: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        ["content_id", "project_id"],
        ["contents.id", "contents.project_id"],
        ondelete="CASCADE",
        name=f"fk_{table}_content",
    )


class ConversionProfile(TimestampMixin, Base):
    """企画×チャネルの書き分けルール（C2）。初めて変換するときに既定値から作る。"""

    __tablename__ = "conversion_profiles"
    __table_args__ = (
        _channel_check("conversion_profiles"),
        UniqueConstraint("project_id", "channel", name="uq_conversion_profiles_project_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    structure: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str] = mapped_column(Text, nullable=False)
    first_person: Mapped[str] = mapped_column(String(50), nullable=False)
    banned_phrases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}


class ConversionJob(TimestampMixin, Base):
    """変換1回＝1行。キューの1件と実行履歴の1行を兼ねる（design.md §3-2・ADR-0017）。"""

    __tablename__ = "conversion_jobs"
    __table_args__ = (
        _channel_check("conversion_jobs"),
        CheckConstraint(_JOB_STATUS_CHECK, name="ck_conversion_jobs_status"),
        _content_fk("conversion_jobs"),
        # 同じコンテンツ×チャネルの二重実行を DB で止める（C3）。
        Index(
            "uq_conversion_jobs_active",
            "content_id",
            "channel",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        # ワーカーが待機中を古い順に拾う経路。
        Index(
            "ix_conversion_jobs_queued",
            "created_at",
            postgresql_where=text("status = 'queued'"),
        ),
        # 1コンテンツの履歴（新しい順）。
        Index("ix_conversion_jobs_content_id", "content_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(nullable=False)
    content_id: Mapped[int] = mapped_column(nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # 変換したときの最新リビジョン番号。contents.version ではない（design.md §3-2）。
    source_revision_no: Mapped[int] = mapped_column(nullable=False)
    # 変換時のプロファイルを丸ごと写す（C2「過去の変換が何で作られたか分かる」）。
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result_title: Mapped[str | None] = mapped_column(Text)
    result_body: Mapped[str | None] = mapped_column(Text)
    result_extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int | None] = mapped_column()
    output_tokens: Mapped[int | None] = mapped_column()

    __mapper_args__ = {"eager_defaults": True}


class ChannelDraft(TimestampMixin, Base):
    """コンテンツ×チャネルで1件のチャネル原稿。公開するのはこれ（C4・design.md §9）。

    本文の正は ``contents.body_md`` のまま。原稿は別の行で、別の楽観ロックを持つ。
    """

    __tablename__ = "channel_drafts"
    __table_args__ = (
        _channel_check("channel_drafts"),
        _content_fk("channel_drafts"),
        UniqueConstraint("content_id", "channel", name="uq_channel_drafts_content_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(nullable=False)
    content_id: Mapped[int] = mapped_column(nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # チャネル固有の項目。Qiita なら {"tags": [...]}。形は schemas で検証する。
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    source_revision_no: Mapped[int] = mapped_column(nullable=False)
    applied_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversion_jobs.id", ondelete="SET NULL")
    )
    # 変換結果を反映したあとに手で直したか。true なら再変換の結果で置き換えない（§9-2）。
    edited_after_apply: Mapped[bool] = mapped_column(nullable=False, default=False)
    # 手直し済みのときに保留にした変換結果。
    pending_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversion_jobs.id", ondelete="SET NULL")
    )
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    __mapper_args__ = {"version_id_col": version, "eager_defaults": True}


class ChannelAccount(TimestampMixin, Base):
    """ユーザー×チャネルの外部トークン（C5）。企画に属さない（design.md §5）。"""

    __tablename__ = "channel_accounts"
    __table_args__ = (
        _channel_check("channel_accounts"),
        UniqueConstraint("user_id", "channel", name="uq_channel_accounts_user_channel"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    # Fernet の暗号文。平文のトークンは DB に置かない（core/crypto.py）。
    encrypted_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    # Qiita のユーザー名（表示用）。
    external_user_id: Mapped[str] = mapped_column(String(200), nullable=False)

    __mapper_args__ = {"eager_defaults": True}


class Publication(TimestampMixin, Base):
    """公開物（C6・C8）。取消は論理削除で、取り消した行も記録として残る。"""

    __tablename__ = "publications"
    __table_args__ = (
        _channel_check("publications"),
        CheckConstraint(_VISIBILITY_CHECK, name="ck_publications_visibility"),
        _content_fk("publications"),
        # 同じコンテンツを同じチャネルに二重に公開しない（C6・C7）。
        Index(
            "uq_publications_active_content_channel",
            "content_id",
            "channel",
            unique=True,
            postgresql_where=text("cancelled_at IS NULL"),
        ),
        # 同じ記事・URL の二重登録（C7）。
        Index(
            "uq_publications_active_external",
            "channel",
            "external_id",
            unique=True,
            postgresql_where=text("cancelled_at IS NULL"),
        ),
        Index("ix_publications_project_published_at", "project_id", "published_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(nullable=False)
    content_id: Mapped[int] = mapped_column(nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    visibility: Mapped[str | None] = mapped_column(String(10))
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    last_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))

    __mapper_args__ = {"eager_defaults": True}
