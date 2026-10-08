"""contents モジュールの Pydantic リクエスト/レスポンススキーマ。

models.py とは意図的に分けている：API 契約の形とテーブルの形は変わる理由が
異なるため（structure.md、ADR-0002 §理由3）。
"""

import re
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.modules.contents.models import ContentStatus, RevisionKind

# 本文の上限。リクエストボディ自体のサイズ制限は前段（リバースプロキシ）を
# 置くまで無いので、ここで頭打ちにしておく。10万字は長い記事でも十分足りる。
BODY_MD_MAX_LENGTH = 100_000

# 1コンテンツのタグ上限は Service が持つ（MAX_TAGS_PER_CONTENT）。ここでは
# リクエストの巨大化だけを止める。
_TAG_IDS_MAX_ITEMS = 50

_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _check_source_note_path(value: str) -> str:
    """Vault からの相対パスだけを通し、区切りを ``/`` にそろえる（design.md §6-6）。

    サービスはこのパスのファイルを読まないし、存在も確かめない（Vault に到達できない）。
    ここで止めるのは「相対パスとして意味を持たないもの」だけ。
    """
    if _CONTROL_CHARS.search(value):
        raise ValueError("must not contain control characters")
    normalized = value.replace("\\", "/")
    if normalized.startswith("/") or _DRIVE_LETTER.match(normalized):
        raise ValueError("must be a path relative to the vault")
    if ".." in normalized.split("/"):
        raise ValueError("must not contain '..'")
    return normalized


SourceNotePath = Annotated[
    str, Field(min_length=1, max_length=500), AfterValidator(_check_source_note_path)
]
TagName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class ContentCreateRequest(BaseModel):
    # 未知フィールドは弾く。黙って捨てると、camelCase で送ったクライアントに
    # 「200 が返るのに保存されていない」という無音の失敗が起きる（design.md §3-3 の
    # 「変更なし PATCH は version 据え置き」と組み合わさると気づけない）。
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    body_md: str = Field(default="", max_length=BODY_MD_MAX_LENGTH)
    tag_ids: list[int] = Field(default_factory=list, max_length=_TAG_IDS_MAX_ITEMS)
    source_note_path: SourceNotePath | None = None


class ContentUpdateRequest(BaseModel):
    """省略したフィールドはそのまま。``expected_version`` は必須で、これにより
    どの更新も楽観ロックをすり抜けられない（design.md §3-3）。

    ``source_note_path`` だけは「省略」と ``null``（消す）を区別する。Router が
    ``model_fields_set`` を見て、送られていなければ触らない。
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body_md: str | None = Field(default=None, max_length=BODY_MD_MAX_LENGTH)
    source_note_path: SourceNotePath | None = None
    expected_version: int


class ContentTagsRequest(BaseModel):
    """タグの付け替え。集合で置き換える（content-pipeline design.md §6-4）。"""

    model_config = ConfigDict(extra="forbid")

    tag_ids: list[int] = Field(max_length=_TAG_IDS_MAX_ITEMS)


class RevisionRestoreRequest(BaseModel):
    """復元も楽観ロックの対象（C7）。"""

    model_config = ConfigDict(extra="forbid")

    expected_version: int


class TagCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: TagName


class TagRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: TagName


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TagWithUsageOut(TagOut):
    """タグ一覧用。生きているコンテンツへの付与件数付き。"""

    content_count: int


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
    tags: list[TagOut]
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
    tags: list[TagOut]
    source_note_path: str | None
    created_by: int
    created_at: datetime
    updated_at: datetime


class RevisionSummaryOut(BaseModel):
    """版の一覧の1行。本文は返さず文字数だけ（content-pipeline design.md §6-1）。"""

    model_config = ConfigDict(from_attributes=True)

    revision_no: int
    title: str
    kind: RevisionKind
    restored_from_no: int | None
    created_by: int
    created_at: datetime
    body_length: int


class RevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    revision_no: int
    title: str
    body_md: str
    kind: RevisionKind
    restored_from_no: int | None
    created_by: int
    created_at: datetime
