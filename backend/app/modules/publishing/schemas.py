"""publishing モジュールの Pydantic リクエスト/レスポンススキーマ。"""

from typing import Annotated

from pydantic import BaseModel, SecretStr, StringConstraints


class QiitaAccountOut(BaseModel):
    """登録状況だけを返す。**トークンは返さない**（C5）。"""

    registered: bool
    external_user_id: str | None = None


class QiitaAccountRegisterRequest(BaseModel):
    # SecretStr にしておくと、repr・ログ・検証エラーに値が出ない。
    token: Annotated[SecretStr, StringConstraints(min_length=1, max_length=200)]
