"""metrics モジュールの ORM モデル（metrics design.md §3・ADR-0008）。

- ``metric_snapshots``：公開物×対象日（JST）で1行。指標は汎用の4列で、チャネルでの意味は
  capabilities が持つ。取れない指標は NULL、取れなかった日は行が無い（0 で埋めない）
- ``job_runs`` / ``job_run_items``：実行1回と、キューの1件（公開物1件・RSS 1回）の2段。
  リトライは item 単位で、``status = 'queued' AND next_run_at <= now()`` を拾う
- ``podcast_feeds`` / ``podcast_episodes``：企画に1つの RSS と、見たエピソードの記録
"""

from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.channels.capabilities import CHANNEL_CHECK_VALUES, METRIC_COLUMNS
from app.core.db import Base, TimestampMixin


class SnapshotSource(StrEnum):
    AUTO = "auto"
    MANUAL = "manual"


class JobKind(StrEnum):
    QIITA_METRICS = "qiita_metrics"
    PODCAST_RSS = "podcast_rss"


class JobTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    RETRY = "retry"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    # 1件でも確定失敗があれば partially_failed。全件失敗なら failed。
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"


class ItemStatus(StrEnum):
    # リトライ待ちも queued のまま next_run_at を未来にする（design.md §3-3）。
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _in(column: str, values: type[StrEnum]) -> str:
    return "{} IN ({})".format(column, ", ".join(f"'{v.value}'" for v in values))


# 実行中の判定。部分 UNIQUE と Repository の両方で使う。
ACTIVE_RUN_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)


class MetricSnapshot(Base):
    """公開物×対象日で1行（S1・ADR-0008）。同じ日の再取得は UPSERT で上書きする。"""

    __tablename__ = "metric_snapshots"
    __table_args__ = (
        CheckConstraint(f"channel IN ({CHANNEL_CHECK_VALUES})", name="ck_metric_snapshots_channel"),
        CheckConstraint(_in("source", SnapshotSource), name="ck_metric_snapshots_source"),
        *(
            CheckConstraint(f"{c} IS NULL OR {c} >= 0", name=f"ck_metric_snapshots_{c}_nonneg")
            for c in METRIC_COLUMNS
        ),
        # 企画をまたぐ参照を DB で止める（publishing §3-3 と同じ）。公開物は論理削除なので
        # 実際に CASCADE が走るのは企画ごと消したときだけ。
        ForeignKeyConstraint(
            ["publication_id", "project_id"],
            ["publications.id", "publications.project_id"],
            ondelete="CASCADE",
            name="fk_metric_snapshots_publication",
        ),
        # ダッシュボードの「企画×直近30日」（design.md §3-4）。
        Index("ix_metric_snapshots_project_captured_on", "project_id", "captured_on"),
    )

    publication_id: Mapped[int] = mapped_column(primary_key=True)
    captured_on: Mapped[date] = mapped_column(Date, primary_key=True)
    # 公開物から写して持つ（非正規化・ADR-0008）。公開物の企画・チャネルは変わらない。
    project_id: Mapped[int] = mapped_column(nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    views: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    stocks: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 手入力した人。自動取得なら NULL。
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))


class JobRun(TimestampMixin, Base):
    """ジョブの実行1回（S4）。履歴と SSE の単位。再実行は新しい行として作る。"""

    __tablename__ = "job_runs"
    __table_args__ = (
        CheckConstraint(_in("kind", JobKind), name="ck_job_runs_kind"),
        CheckConstraint(_in("trigger", JobTrigger), name="ck_job_runs_trigger"),
        CheckConstraint(_in("status", RunStatus), name="ck_job_runs_status"),
        # 定期投入はプロセスが複数あっても1日1回（S2・ADR-0013）。
        Index(
            "uq_job_runs_scheduled_daily",
            "project_id",
            "kind",
            "target_date",
            unique=True,
            postgresql_where=text("trigger = 'scheduled'"),
        ),
        # 同じ企画で同じ種類が二重に走らない（S4 の 409）。
        Index(
            "uq_job_runs_active",
            "project_id",
            "kind",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
        # 実行履歴の一覧（新しい順）。
        Index("ix_job_runs_project_created_at", "project_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), nullable=False)
    # JST の日付。手動実行・再実行でも「その日」で、同じ日のスナップショットを上書きする。
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    # 手動実行・再実行はその人。定期実行は NULL（design.md §5-2）。
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    # 再実行の元になった run（trigger = retry のときだけ）。
    retry_of: Mapped[int | None] = mapped_column(ForeignKey("job_runs.id", ondelete="SET NULL"))
    # item が確定するたびに同じトランザクションで足す（SSE が毎回 COUNT しなくて済むように）。
    total: Mapped[int] = mapped_column(nullable=False, server_default="0")
    succeeded: Mapped[int] = mapped_column(nullable=False, server_default="0")
    failed: Mapped[int] = mapped_column(nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __mapper_args__ = {"eager_defaults": True}


class JobRunItem(TimestampMixin, Base):
    """キューの1件（S3）。公開物1件の指標取得、または RSS の取得1回。"""

    __tablename__ = "job_run_items"
    __table_args__ = (
        CheckConstraint(_in("status", ItemStatus), name="ck_job_run_items_status"),
        CheckConstraint("attempts >= 0", name="ck_job_run_items_attempts_nonneg"),
        # publication_id が NULL（RSS の取得）のときは FK を見ない（MATCH SIMPLE）。
        ForeignKeyConstraint(
            ["publication_id", "project_id"],
            ["publications.id", "publications.project_id"],
            ondelete="CASCADE",
            name="fk_job_run_items_publication",
        ),
        # ワーカーが拾う経路（design.md §6-1 ②）。
        Index(
            "ix_job_run_items_queued",
            "next_run_at",
            postgresql_where=text("status = 'queued'"),
        ),
        Index("ix_job_run_items_run_id", "run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("job_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[int] = mapped_column(nullable=False)
    publication_id: Mapped[int | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempts: Mapped[int] = mapped_column(nullable=False, server_default="0")
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(Text)

    __mapper_args__ = {"eager_defaults": True}


class PodcastFeed(TimestampMixin, Base):
    """企画に1つのポッドキャスト RSS（S6）。"""

    __tablename__ = "podcast_feeds"
    __table_args__ = (UniqueConstraint("project_id", name="uq_podcast_feeds_project"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    # 取り込みはこの人として認可を通し直す（design.md §5-2）。
    registered_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __mapper_args__ = {"eager_defaults": True}


class PodcastEpisode(Base):
    """見たエピソードの記録（S6）。公開物を取り消しても行が残るので、次の取り込みで復活しない。

    RSS の登録を削除すると CASCADE で消える。登録し直したときは、取り消したエピソードも
    もう一度取り込まれる（登録し直す＝最初から取り込み直す、と扱う）。
    """

    __tablename__ = "podcast_episodes"
    __table_args__ = (UniqueConstraint("feed_id", "guid", name="uq_podcast_episodes_feed_guid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    feed_id: Mapped[int] = mapped_column(
        ForeignKey("podcast_feeds.id", ondelete="CASCADE"), nullable=False
    )
    # guid → enclosure の URL → link の順で決めた識別子（design.md §8-1）。
    guid: Mapped[str] = mapped_column(String(2000), nullable=False)
    publication_id: Mapped[int | None] = mapped_column(
        ForeignKey("publications.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
