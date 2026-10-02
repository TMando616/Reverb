"""非同期エンジンとセッションファクトリ。

ここから import してよいのは ``repository.py`` / ``models.py`` / ``deps.py`` /
``cli.py`` / ``migrations/`` のみ（design.md §2-2）。``.importlinter`` が機械的に
禁じているのは Service からの import だけで、**router / schemas から
``async_session`` を掴む経路は契約で止まらない**。ここは規約として守る。
"""

from collections.abc import AsyncIterator
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.config import get_settings

engine = create_async_engine(
    get_settings().database_url,
    future=True,
    # アイドルで切れた接続・フェイルオーバー後の死んだ接続をリクエストに渡さない。
    # 入れていないと、最初のステートメントが 500 になる状態がプールの入れ替わりまで続く。
    pool_pre_ping=True,
)
async_session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """全 ORM モデルの宣言的ベースクラス。"""


class TimestampMixin:
    """``created_at`` / ``updated_at`` を DB 側で埋める（design.md §3-1）。

    タイムスタンプは ``timestamptz``。``created_at`` はサーバークロックが責務を持つ
    ので、アプリ外（CLI・マイグレーション）から入れた行でも埋まる。

    一方 ``updated_at`` の更新は ORM の ``onupdate`` だけが担っている（DB トリガーは
    無い）。psql や ``op.execute("UPDATE ...")`` で直接書くと古い値が残る。
    履歴の正しさが要るようになったらトリガーを足す。
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI の dependency：1リクエスト＝1セッション＝1トランザクション。

    Service は flush はするが commit はしない（design.md §4-4）。唯一の
    ``commit()`` はここにあり、ハンドラが例外を出さずに戻ったときだけ実行される。
    FastAPI は yield 後のコードをレスポンス送信後に走らせるため、書き込み系の
    Service はここに戻る前に ``flush()`` しておく必要がある。そうすれば
    制約違反・楽観ロック競合がハンドラ側でまだ 4xx に変換できるタイミングで
    表面化する（design.md §4-4）。
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
