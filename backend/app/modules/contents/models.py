"""contents モジュールの ORM モデル（コンテンツ CRUD・状態遷移）。

テーブル定義は foundation スペックでここに置く（design.md §3）。モジュール内で
``sqlalchemy`` を import できるのはこのファイルと repository.py だけ。
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class ContentStatus(StrEnum):
    """コード上の識別子は英語。UI がこれを日本語ラベルに対応づける（design.md §3-2）。"""

    INBOX = "inbox"
    ADOPTED = "adopted"
    DRAFTING = "drafting"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    SHELVED = "shelved"


# 素の文字列カラム + アプリ側 StrEnum を CHECK 制約で守る形にしているので、
# status を増やすときも ENUM 型のマイグレーションが要らない（design.md §3-2）。
_STATUS_CHECK = "status IN ({})".format(", ".join(f"'{s.value}'" for s in ContentStatus))


class Content(TimestampMixin, Base):
    """1つの企画の中で inbox から published まで動くコンテンツ。

    ``version`` は SQLAlchemy の ``version_id_col``：flush される UPDATE は
    毎回 ``WHERE version = ?`` を伴い、version を +1 する。これが二段の楽観ロックの
    後半段にあたる（design.md §3-3）。削除は ``deleted_at`` による論理削除。
    """

    __tablename__ = "contents"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_contents_status"),
        # 主要な読み取り経路：1企画のコンテンツを、任意で status 絞り込み付きで
        # 取得する（design.md §3-2）。
        Index("ix_contents_project_id_status", "project_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __mapper_args__ = {
        "version_id_col": version,
        # INSERT / UPDATE の RETURNING でサーバー生成値（created_at / updated_at）
        # を取得する。これを付けないと flush 後にこれらが expire され、レスポンス
        # のために読んだ瞬間に暗黙の非同期ロードが走ってしまう。
        "eager_defaults": True,
    }


class ContentStatusTransition(Base):
    """状態遷移の追記専用ログ。遷移1回につき1行（design.md §8-2）。

    本文の履歴（``content_revisions``、後続スペック）とは別テーブルにしている。
    2つは変更される理由が違うため（design.md §3-2）。
    """

    __tablename__ = "content_status_transitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(
        ForeignKey("contents.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
