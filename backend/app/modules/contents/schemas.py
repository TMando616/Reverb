"""Pydantic request/response schemas for the contents module.

Kept separate from models.py on purpose: the shape of the API contract and the
shape of a table change for different reasons (structure.md, ADR-0002 §理由3).
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.contents.models import ContentStatus


class ContentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body_md: str = ""


class ContentUpdateRequest(BaseModel):
    """Omitted fields stay as they are. ``expected_version`` is mandatory so no
    update can skip the optimistic lock (design.md §3-3).
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body_md: str | None = None
    expected_version: int


class ContentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    body_md: str
    status: ContentStatus
    # Echoed so the client can send it back as the next ``expected_version``.
    version: int
    created_by: int
    created_at: datetime
    updated_at: datetime
