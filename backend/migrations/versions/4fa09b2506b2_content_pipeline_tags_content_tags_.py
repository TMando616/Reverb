"""content-pipeline: tags, content_tags, content_revisions, source_note_path

Revision ID: 4fa09b2506b2
Revises: a267b3c77051
Create Date: 2026-10-10 12:54:51.714709
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4fa09b2506b2"
down_revision: str | None = "a267b3c77051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ### Alembic が自動生成したコマンドを手で並べ替えた ###
    # content_tags の複合 FK が参照するので、contents 側の UNIQUE (id, project_id) を
    # 先に作る（autogenerate は ALTER をテーブル作成の後ろに置くため、そのままだと失敗する）。
    op.add_column("contents", sa.Column("source_note_path", sa.String(length=500), nullable=True))
    op.create_unique_constraint("uq_contents_id_project", "contents", ["id", "project_id"])
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("name_key", sa.String(length=200), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "project_id", name="uq_tags_id_project"),
        sa.UniqueConstraint("project_id", "name_key", name="uq_tags_project_name_key"),
    )
    op.create_table(
        "content_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("restored_from_no", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('create', 'save', 'restore')", name="ck_content_revisions_kind"
        ),
        sa.ForeignKeyConstraint(["content_id"], ["contents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("content_id", "revision_no", name="uq_content_revisions_content_no"),
    )
    op.create_table(
        "content_tags",
        sa.Column("content_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["content_id", "project_id"],
            ["contents.id", "contents.project_id"],
            name="fk_content_tags_content",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id", "project_id"],
            ["tags.id", "tags.project_id"],
            name="fk_content_tags_tag",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("content_id", "tag_id"),
    )
    op.create_index("ix_content_tags_tag_id", "content_tags", ["tag_id"], unique=False)

    # 既存のコンテンツに初版（revision_no = 1・kind = create）を1件ずつ作る。
    # 初版が無いコンテンツを作らないため（content-pipeline design.md §3-2）。
    # 論理削除済みも含める：復元はしないが、版が「無い」行を例外として扱わずに済む。
    op.execute(
        """
        INSERT INTO content_revisions (content_id, revision_no, title, body_md, kind, created_by)
        SELECT id, 1, title, body_md, 'create', created_by FROM contents
        """
    )
    # ### ここまで ###


def downgrade() -> None:
    # upgrade の逆順。content_tags を消してから contents 側の UNIQUE を外す。
    op.drop_index("ix_content_tags_tag_id", table_name="content_tags")
    op.drop_table("content_tags")
    op.drop_table("content_revisions")
    op.drop_table("tags")
    op.drop_constraint("uq_contents_id_project", "contents", type_="unique")
    op.drop_column("contents", "source_note_path")
