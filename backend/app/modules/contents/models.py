"""contents モジュールの ORM モデル（コンテンツ CRUD・状態遷移）。

テーブル定義は foundation スペックでここに置く（design.md §3）。モジュール内で
``sqlalchemy`` を import できるのはこのファイルと repository.py だけ。
"""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin


class ContentStatus(StrEnum):
    """コード上の識別子は英語。UI がこれを日本語ラベルに対応づける（design.md §3-2）。"""

    INBOX = "inbox"
    ADOPTED = "adopted"
    DRAFTING = "drafting"
    IN_REVIEW = "in_review"
    PUBLISHED = "published"
    SHELVED = "shelved"


# 素の文字列カラム + アプリ側 StrEnum を CHECK 制約で守る形にしているので、
# status を増やすときも ENUM 型のマイグレーションが要らない（design.md §3-2）。
_STATUS_CHECK = "status IN ({})".format(", ".join(f"'{s.value}'" for s in ContentStatus))


class RevisionKind(StrEnum):
    """リビジョンができた理由（content-pipeline design.md §3-2）。"""

    CREATE = "create"  # 作成時の初版
    SAVE = "save"  # 自動保存・手動保存
    RESTORE = "restore"  # 過去の版からの復元


_REVISION_KIND_CHECK = "kind IN ({})".format(", ".join(f"'{k.value}'" for k in RevisionKind))


class Content(TimestampMixin, Base):
    """1つの企画の中で inbox から published まで動くコンテンツ。

    ``version`` は SQLAlchemy の ``version_id_col``：flush される UPDATE は
    毎回 ``WHERE version = ?`` を伴い、version を +1 する。これが二段の楽観ロックの
    後半段にあたる（design.md §3-3）。削除は ``deleted_at`` による論理削除。
    """

    __tablename__ = "contents"
    __table_args__ = (
        CheckConstraint(_STATUS_CHECK, name="ck_contents_status"),
        # 主要な読み取り経路：1企画のコンテンツを、任意で status 絞り込み付きで
        # 取得する（design.md §3-2）。
        Index("ix_contents_project_id_status", "project_id", "status"),
        # content_tags の複合 FK の参照先。id が PK なので値としては冗長だが、
        # FK の参照先には UNIQUE が要る（content-pipeline design.md §3-3）。
        UniqueConstraint("id", "project_id", name="uq_contents_id_project"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 元 Obsidian ノートの Vault からの相対パス。サービスはこのファイルを読まない（C4）。
    source_note_path: Mapped[str | None] = mapped_column(String(500))

    # 読み取り専用。書き込みは ContentTag の行を直接足し引きする（project_id を
    # 自分で埋める必要があるため）。lazy="raise" で、selectinload を忘れたときに
    # 暗黙の遅延ロード（async では MissingGreenlet）ではなく例外にする（design.md §6-5）。
    tags: Mapped[list["Tag"]] = relationship(
        secondary="content_tags",
        primaryjoin="Content.id == foreign(ContentTag.content_id)",
        secondaryjoin="Tag.id == foreign(ContentTag.tag_id)",
        order_by="Tag.name",
        viewonly=True,
        lazy="raise",
    )

    __mapper_args__ = {
        "version_id_col": version,
        # INSERT / UPDATE の RETURNING でサーバー生成値（created_at / updated_at）
        # を取得する。これを付けないと flush 後にこれらが expire され、レスポンス
        # のために読んだ瞬間に暗黙の非同期ロードが走ってしまう。
        "eager_defaults": True,
    }


class ContentStatusTransition(Base):
    """状態遷移の追記専用ログ。遷移1回につき1行（design.md §8-2）。

    本文の履歴（``content_revisions``、後続スペック）とは別テーブルにしている。
    2つは変更される理由が違うため（design.md §3-2）。
    """

    __tablename__ = "content_status_transitions"
    __table_args__ = (
        # 「1コンテンツの履歴」を引く経路（後続スペック）と、contents 側の
        # ON DELETE CASCADE のため。FK の参照側に索引が無いと、親の削除が
        # このテーブルの全走査になる。
        Index("ix_content_status_transitions_content_id", "content_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(
        ForeignKey("contents.id", ondelete="CASCADE"), nullable=False
    )
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Tag(TimestampMixin, Base):
    """企画ごとのタグ（content-pipeline design.md §3-2）。

    ``name`` は入力どおりの表示名、``name_key`` は同一判定用の正規化キー
    （NFKC → casefold → 前後空白除去）。「Python」と「python」を別タグにしない。
    """

    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("project_id", "name_key", name="uq_tags_project_name_key"),
        UniqueConstraint("id", "project_id", name="uq_tags_id_project"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # NFKC で文字数が増えることがある（「㍿」→「株式会社」）ので、表示名より長く取る。
    name_key: Mapped[str] = mapped_column(String(200), nullable=False)

    __mapper_args__ = {"eager_defaults": True}


class ContentTag(Base):
    """コンテンツとタグの中間テーブル。

    ``project_id`` を両方の複合 FK に使うので、**コンテンツとタグの企画が違う行は
    INSERT できない**（content-pipeline design.md §3-3）。Service の確認が漏れても
    ここで止まる。
    """

    __tablename__ = "content_tags"
    __table_args__ = (
        ForeignKeyConstraint(
            ["content_id", "project_id"],
            ["contents.id", "contents.project_id"],
            ondelete="CASCADE",
            name="fk_content_tags_content",
        ),
        ForeignKeyConstraint(
            ["tag_id", "project_id"],
            ["tags.id", "tags.project_id"],
            ondelete="CASCADE",
            name="fk_content_tags_tag",
        ),
        # タグでの絞り込みと、タグ削除時の CASCADE のため。
        Index("ix_content_tags_tag_id", "tag_id"),
    )

    content_id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContentRevision(Base):
    """本文（title / body_md）の全文スナップショット。追記専用（C7）。

    状態遷移のログ（``content_status_transitions``）とは別。変更される理由が違うため
    （foundation design.md §3-2）。``revision_no`` はコンテンツ内の連番で、URL に出す番号。
    """

    __tablename__ = "content_revisions"
    __table_args__ = (
        CheckConstraint(_REVISION_KIND_CHECK, name="ck_content_revisions_kind"),
        UniqueConstraint("content_id", "revision_no", name="uq_content_revisions_content_no"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    content_id: Mapped[int] = mapped_column(
        ForeignKey("contents.id", ondelete="CASCADE"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    # kind = restore のときだけ、復元元の版番号が入る。
    restored_from_no: Mapped[int | None] = mapped_column()
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __mapper_args__ = {"eager_defaults": True}
