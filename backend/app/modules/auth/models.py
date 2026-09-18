"""auth モジュールの ORM モデル（認証・現在のユーザー解決）。

テーブル定義は foundation スペックでここに置く（design.md §3）。モジュール内で
``sqlalchemy`` を import できるのはこのファイルと repository.py だけ。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin


class User(TimestampMixin, Base):
    """ログイン可能な人物。行が作られるのは招待受諾または bootstrap CLI のみ ──
    自己登録エンドポイントは存在しない（F2）。
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # demo アカウントは role に関わらず読み取り専用に固定される（design.md §5-2）。
    is_demo: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")


class Session(Base):
    """オペークトークンのセッション。保存するのは ``sha256(token)`` だけ
    （design.md §4-1）。``revoked_at`` によりログアウトが即座に効く（F1）。
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(lazy="raise")
