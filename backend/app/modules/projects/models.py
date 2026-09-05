"""ORM models for the projects module (企画・メンバー・招待).

Tables land here in the foundation spec (design.md §3). Only this file and
repository.py may import ``sqlalchemy`` inside a module.
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

# Single source for the DB-side CHECK: the role column is a plain string plus an
# app-level ``Role`` StrEnum, so values can change without a migration on an
# ENUM type (design.md §3-2).
_ROLE_VALUES = tuple(r.value for r in Role)
_ROLE_CHECK = "role IN ({})".format(", ".join(f"'{v}'" for v in _ROLE_VALUES))


class Project(TimestampMixin, Base):
    """A publishing project. Its creator becomes the first ``owner`` member in
    the same transaction (design.md §9-3); non-members are shown a 404 (§5-2).
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )


class ProjectMember(Base):
    """Join row between a user and a project carrying a ``role``.

    ``UNIQUE (project_id, user_id)`` is what makes "no duplicate membership"
    (F2) a database guarantee; invitation acceptance relies on it via
    ``ON CONFLICT DO NOTHING`` (design.md §9-2).
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
    # Indexed on its own: resolving "which projects am I in / what is my role"
    # is on every authorized request (design.md §3-2 / §5-2).
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Invitation(Base):
    """A link-only invitation (design.md §9-1). Only ``sha256(token)`` is stored;
    the raw token in the accept URL is the sole bearer of authority. Invalid /
    expired / already-accepted tokens all resolve to the same 404 (§6-3).
    """

    __tablename__ = "invitations"
    __table_args__ = (CheckConstraint(_ROLE_CHECK, name="ck_invitations_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Recorded for the operator's reference only; M0 has no mail delivery (§9-1).
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
