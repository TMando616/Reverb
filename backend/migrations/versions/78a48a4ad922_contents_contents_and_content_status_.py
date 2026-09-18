"""contents: contents and content_status_transitions

Revision ID: 78a48a4ad922
Revises: 21a399cb7858
Create Date: 2026-09-13 04:45:02.624985
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "78a48a4ad922"
down_revision: str | None = "21a399cb7858"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ### Alembic が自動生成したコマンド ── 必要なら調整すること ###
    op.create_table(
        "contents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body_md", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('inbox', 'adopted', 'drafting', 'in_review', 'published', 'shelved')",
            name="ck_contents_status",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_contents_project_id_status", "contents", ["project_id", "status"], unique=False
    )
    op.create_table(
        "content_status_transitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=False),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # ### Alembic のコマンドはここまで ###


def downgrade() -> None:
    # ### Alembic が自動生成したコマンド ── 必要なら調整すること ###
    op.drop_table("content_status_transitions")
    op.drop_index("ix_contents_project_id_status", table_name="contents")
    op.drop_table("contents")
    # ### Alembic のコマンドはここまで ###
