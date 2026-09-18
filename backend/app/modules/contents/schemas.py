"""contents モジュールの Pydantic リクエスト/レスポンススキーマ。

models.py とは意図的に分けている：API 契約の形とテーブルの形は変わる理由が
異なるため（structure.md、ADR-0002 §理由3）。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.contents.models import ContentStatus


class ContentCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body_md: str = ""


class ContentUpdateRequest(BaseModel):
    """省略したフィールドはそのまま。``expected_version`` は必須で、これにより
    どの更新も楽観ロックをすり抜けられない（design.md §3-3）。
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
    # クライアントが次の ``expected_version`` としてそのまま送り返せるよう返す。
    version: int
    created_by: int
    created_at: datetime
    updated_at: datetime
