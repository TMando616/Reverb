"""contents モジュールの Pydantic リクエスト/レスポンススキーマ。

models.py とは意図的に分けている：API 契約の形とテーブルの形は変わる理由が
異なるため（structure.md、ADR-0002 §理由3）。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.contents.models import ContentStatus

# 本文の上限。リクエストボディ自体のサイズ制限は前段（リバースプロキシ）を
# 置くまで無いので、ここで頭打ちにしておく。10万字は長い記事でも十分足りる。
BODY_MD_MAX_LENGTH = 100_000


class ContentCreateRequest(BaseModel):
    # 未知フィールドは弾く。黙って捨てると、camelCase で送ったクライアントに
    # 「200 が返るのに保存されていない」という無音の失敗が起きる（design.md §3-3 の
    # 「変更なし PATCH は version 据え置き」と組み合わさると気づけない）。
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    body_md: str = Field(default="", max_length=BODY_MD_MAX_LENGTH)


class ContentUpdateRequest(BaseModel):
    """省略したフィールドはそのまま。``expected_version`` は必須で、これにより
    どの更新も楽観ロックをすり抜けられない（design.md §3-3）。
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body_md: str | None = Field(default=None, max_length=BODY_MD_MAX_LENGTH)
    expected_version: int


class ContentTransitionRequest(BaseModel):
    """遷移先と、読み込んだときの version。遷移も楽観ロックの対象（design.md §8-2）。"""

    model_config = ConfigDict(extra="forbid")

    to: ContentStatus
    expected_version: int


class ContentListItem(BaseModel):
    """一覧用。**``body_md`` を含めない。**

    一覧は企画詳細を開くたびに引かれるが、画面が使うのは id / title / status /
    version だけ。本文を載せると、下書きが増えるほど1回の描画で数 MB が流れる。
    本文が要るときは単体取得（``GET .../contents/{id}``）を使う。
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    status: ContentStatus
    version: int
    created_by: int
    created_at: datetime
    updated_at: datetime


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
