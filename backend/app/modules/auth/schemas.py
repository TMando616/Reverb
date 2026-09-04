"""Pydantic request/response schemas for the auth module.

Kept separate from models.py on purpose: the shape of the API contract and the
shape of a table change for different reasons (structure.md, ADR-0002 §理由3).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    """The caller summary embedded in the login response (design.md §6-2)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str
    is_demo: bool


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime
    user: UserOut


class MeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    is_demo: bool
