"""metrics: snapshots, job runs, podcast feeds

Revision ID: b1abd983f782
Revises: 88c7f471219d
Create Date: 2026-11-03 04:40:06.418781
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1abd983f782"
down_revision: str | None = "88c7f471219d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 複合 FK (publication_id, project_id) の参照先。FK より先に作る（autogenerate は後ろに置く）。
    op.create_unique_constraint("uq_publications_id_project", "publications", ["id", "project_id"])
    op.create_table(
        "job_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=True),
        sa.Column("retry_of", sa.Integer(), nullable=True),
        sa.Column("total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("succeeded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('qiita_metrics', 'podcast_rss')", name="ck_job_runs_kind"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partially_failed', 'failed')",
            name="ck_job_runs_status",
        ),
        sa.CheckConstraint(
            "trigger IN ('scheduled', 'manual', 'retry')", name="ck_job_runs_trigger"
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["retry_of"], ["job_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_runs_project_created_at", "job_runs", ["project_id", "created_at"], unique=False
    )
    op.create_index(
        "uq_job_runs_active",
        "job_runs",
        ["project_id", "kind"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_index(
        "uq_job_runs_scheduled_daily",
        "job_runs",
        ["project_id", "kind", "target_date"],
        unique=True,
        postgresql_where=sa.text("trigger = 'scheduled'"),
    )
    op.create_table(
        "podcast_feeds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("registered_by", sa.Integer(), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["registered_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_podcast_feeds_project"),
    )
    op.create_table(
        "job_run_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_job_run_items_status"
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_job_run_items_attempts_nonneg"),
        sa.ForeignKeyConstraint(
            ["publication_id", "project_id"],
            ["publications.id", "publications.project_id"],
            name="fk_job_run_items_publication",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["job_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_run_items_queued",
        "job_run_items",
        ["next_run_at"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index("ix_job_run_items_run_id", "job_run_items", ["run_id"], unique=False)
    op.create_table(
        "metric_snapshots",
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("captured_on", sa.Date(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("views", sa.BigInteger(), nullable=True),
        sa.Column("likes", sa.BigInteger(), nullable=True),
        sa.Column("stocks", sa.BigInteger(), nullable=True),
        sa.Column("comments", sa.BigInteger(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "channel IN ('qiita', 'x', 'note', 'podcast')", name="ck_metric_snapshots_channel"
        ),
        sa.CheckConstraint("source IN ('auto', 'manual')", name="ck_metric_snapshots_source"),
        sa.CheckConstraint(
            "comments IS NULL OR comments >= 0", name="ck_metric_snapshots_comments_nonneg"
        ),
        sa.CheckConstraint("likes IS NULL OR likes >= 0", name="ck_metric_snapshots_likes_nonneg"),
        sa.CheckConstraint(
            "stocks IS NULL OR stocks >= 0", name="ck_metric_snapshots_stocks_nonneg"
        ),
        sa.CheckConstraint("views IS NULL OR views >= 0", name="ck_metric_snapshots_views_nonneg"),
        sa.ForeignKeyConstraint(
            ["publication_id", "project_id"],
            ["publications.id", "publications.project_id"],
            name="fk_metric_snapshots_publication",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("publication_id", "captured_on"),
    )
    op.create_index(
        "ix_metric_snapshots_project_captured_on",
        "metric_snapshots",
        ["project_id", "captured_on"],
        unique=False,
    )
    op.create_table(
        "podcast_episodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("feed_id", sa.Integer(), nullable=False),
        sa.Column("guid", sa.String(length=2000), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["feed_id"], ["podcast_feeds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("feed_id", "guid", name="uq_podcast_episodes_feed_guid"),
    )


def downgrade() -> None:
    op.drop_table("podcast_episodes")
    op.drop_index("ix_metric_snapshots_project_captured_on", table_name="metric_snapshots")
    op.drop_table("metric_snapshots")
    op.drop_index("ix_job_run_items_run_id", table_name="job_run_items")
    op.drop_index(
        "ix_job_run_items_queued",
        table_name="job_run_items",
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.drop_table("job_run_items")
    op.drop_table("podcast_feeds")
    op.drop_index(
        "uq_job_runs_scheduled_daily",
        table_name="job_runs",
        postgresql_where=sa.text("trigger = 'scheduled'"),
    )
    op.drop_index(
        "uq_job_runs_active",
        table_name="job_runs",
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.drop_index("ix_job_runs_project_created_at", table_name="job_runs")
    op.drop_table("job_runs")
    # 参照していた FK が消えてから外す。
    op.drop_constraint("uq_publications_id_project", "publications", type_="unique")
