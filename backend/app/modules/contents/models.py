"""ORM models for the contents module (コンテンツ CRUD・状態遷移).

Tables land here in the foundation spec (design.md §3). Only this file and
repository.py may import ``sqlalchemy`` inside a module.
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TimestampMixin


class ContentStatus(StrEnum):
    """English identifiers in code; the UI maps them to Japanese labels (design.md §3-2)."""

    INBOX = "inbox"
    ADOPTED = "adopted"
    DRAFTING = "drafting"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    SHELVED = "shelved"


# Plain string column + app-level StrEnum, guarded by a CHECK, so adding a status
# never needs a migration on an ENUM type (design.md §3-2).
_STATUS_CHECK = "status IN ({})".format(", ".join(f"'{s.value}'" for s in ContentStatus))


class Content(TimestampMixin, Base):
    """A piece of content that moves from inbox to published inside one project.

    ``version`` is SQLAlchemy's ``version_id_col``: every flushed UPDATE carries
    ``WHERE version = ?`` and bumps it, which is the second half of the two-stage
    optimistic lock (design.md §3-3). Deletion is logical via ``deleted_at``.
    """

    __tablename__ = "contents"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_contents_status"),
        # The main read path: one project's contents, optionally by status (design.md §3-2).
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
        # Fetch server-generated values (created_at / updated_at) via RETURNING on
        # INSERT and UPDATE. Without it they are expired after flush and reading
        # them for the response would trigger an implicit async load.
        "eager_defaults": True,
    }


class ContentStatusTransition(Base):
    """Append-only log of status changes, one row per transition (design.md §8-2).

    Kept apart from the body history (``content_revisions``, a later spec)
    because the two change for different reasons (design.md §3-2).
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
