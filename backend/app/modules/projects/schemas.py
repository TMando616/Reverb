"""Pydantic request/response schemas for the projects module.

Kept separate from models.py on purpose: the shape of the API contract and the
shape of a table change for different reasons (structure.md, ADR-0002 §理由3).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import Role


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    """A project with the caller's own role attached (design.md §6-1)."""

    id: int
    name: str
    role: Role
    created_at: datetime


class InvitationCreateRequest(BaseModel):
    role: Role
    # Recorded only; M0 sends nothing. A free-form string, not EmailStr, to keep
    # the optional email-validator dependency out of the build (design.md §9-1).
    email: str | None = Field(default=None, max_length=320)


class InvitationOut(BaseModel):
    """The accept path is the only place the raw token appears (design.md §9-1)."""

    accept_path: str
    role: Role
    email: str | None
    expires_at: datetime


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    display_name: str
    email: str
    role: Role
    joined_at: datetime


class MemberRoleUpdateRequest(BaseModel):
    role: Role


class MemberRoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    role: Role


class InvitationAcceptRequest(BaseModel):
    # Required only on the anonymous path; the service enforces that (design.md §9-1).
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    password: str | None = Field(default=None, min_length=1)


class InvitationAcceptOut(BaseModel):
    project_id: int
    # The role actually held — may differ from the invitation's (design.md §9-2).
    role: Role
