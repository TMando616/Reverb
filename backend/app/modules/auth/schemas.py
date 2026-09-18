"""auth モジュールの Pydantic リクエスト/レスポンススキーマ。

models.py とは意図的に分けている：API 契約の形とテーブルの形は変わる理由が
異なるため（structure.md、ADR-0002 §理由3）。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    """ログインレスポンスに埋め込む呼び出し元の要約（design.md §6-2）。"""

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
