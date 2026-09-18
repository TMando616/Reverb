"""projects モジュールの Pydantic リクエスト/レスポンススキーマ。

models.py とは意図的に分けている：API 契約の形とテーブルの形は変わる理由が
異なるため（structure.md、ADR-0002 §理由3）。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.authorization import Role


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    """呼び出し元自身の role を添えた企画（design.md §6-1）。"""

    id: int
    name: str
    role: Role
    created_at: datetime


class InvitationCreateRequest(BaseModel):
    role: Role
    # 記録のみ。M0 では送信しない。任意のメール送信基盤を依存に増やさないため、
    # EmailStr ではなく自由記述の文字列にしている（design.md §9-1）。
    email: str | None = Field(default=None, max_length=320)


class InvitationOut(BaseModel):
    """生のトークンが現れる唯一の場所が accept_path（design.md §9-1）。"""

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
    # 未ログイン経路でのみ必須。その強制は service 側が行う（design.md §9-1）。
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    password: str | None = Field(default=None, min_length=1)


class InvitationAcceptOut(BaseModel):
    project_id: int
    # 実際に保持している role ── 招待の role とは異なることがある（design.md §9-2）。
    role: Role
