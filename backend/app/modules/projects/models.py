"""projects モジュールの ORM モデル（企画・メンバー・招待）。

テーブル定義は foundation スペックでここに置く（design.md §3）。モジュール内で
``sqlalchemy`` を import できるのはこのファイルと repository.py だけ。
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.authorization import Role
from app.core.db import Base, TimestampMixin

# DB 側の CHECK 制約の唯一の源：role カラムは素の文字列 + アプリ側の
# ``Role`` StrEnum なので、値の増減が ENUM 型のマイグレーションを要らなくする
# （design.md §3-2）。
_ROLE_VALUES = tuple(r.value for r in Role)
_ROLE_CHECK = "role IN ({})".format(", ".join(f"'{v}'" for v in _ROLE_VALUES))


class Project(TimestampMixin, Base):
    """発信の企画。作成者は同一トランザクション内で最初の ``owner`` メンバーになる
    （design.md §9-3）。非メンバーには 404 を返す（§5-2）。
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class ProjectMember(Base):
    """ユーザーと企画を ``role`` 付きで結ぶ中間テーブルの行。

    ``UNIQUE (project_id, user_id)`` が「重複メンバーシップを作らない」（F2）を
    DB レベルで保証する。招待受諾はこれに ``ON CONFLICT DO NOTHING`` で乗っている
    （design.md §9-2）。
    """

    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_members_project_user"),
        CheckConstraint(_ROLE_CHECK, name="ck_project_members_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # 単独でインデックスを張る：「自分がどの企画のメンバーで role は何か」の解決は
    # 認可済みリクエストのたびに走る（design.md §3-2 / §5-2）。
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Invitation(Base):
    """リンク方式のみの招待（design.md §9-1）。保存するのは ``sha256(token)`` だけで、
    受諾 URL に載る生のトークンだけが権限の唯一の担い手。無効・期限切れ・
    受諾済みのトークンはすべて同じ 404 に解決される（§6-3）。
    """

    __tablename__ = "invitations"
    __table_args__ = (CheckConstraint(_ROLE_CHECK, name="ck_invitations_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # 運用者の参照用に記録するだけ。M0 にはメール送信基盤が無い（§9-1）。
    email: Mapped[str | None] = mapped_column(String(320))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
