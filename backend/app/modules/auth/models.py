"""ORM models for the auth module (認証・現在のユーザー解決).

Tables land here in the foundation spec (design.md §3). Only this file and
repository.py may import ``sqlalchemy`` inside a module.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin


class User(TimestampMixin, Base):
    """A person who can sign in. Rows are created only via invitation acceptance
    or the bootstrap CLI — there is no self-registration endpoint (F2).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Demo accounts are clamped to read-only regardless of role (design.md §5-2).
    is_demo: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")


class Session(Base):
    """An opaque-token session. Only ``sha256(token)`` is stored (design.md §4-1);
    ``revoked_at`` lets logout take effect immediately (F1).
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
