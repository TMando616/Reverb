"""共有のテストフィクスチャ。

DB を使うテストは専用データベース（既定 ``reverb_test``）に対して走り、1テスト＝
1トランザクションで、終わったらロールバックする。アプリ側の ``get_session`` は
リクエストごとに ``commit()`` するので、素朴に外側トランザクションを張るだけでは
ロールバックが効かない。``join_transaction_mode="create_savepoint"`` を使い、
アプリの commit を SAVEPOINT の解放に変換する（design.md §13-1）。
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator

import pytest
from app.core.db import Base, get_session
from app.core.security import hash_password
from app.main import create_app
from app.modules.auth import models as _auth_models  # noqa: F401  # Base.metadata への登録
from app.modules.auth.models import User
from app.modules.contents import models as _contents_models  # noqa: F401
from app.modules.projects import models as _projects_models  # noqa: F401
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

# 開発用の DB を壊さないよう、テストは別データベースを使う。コンテナ内・CI から
# 走らせるときは TEST_DATABASE_URL でホスト名を差し替える。
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://reverb:reverb@localhost:5432/reverb_test"
)
_ADMIN_URL = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
_TEST_DB_NAME = TEST_DATABASE_URL.rsplit("/", 1)[1]

PASSWORD = "correct-horse-battery-staple"


async def _create_database_if_missing() -> None:
    engine = create_async_engine(_ADMIN_URL, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": _TEST_DB_NAME}
            )
            if exists.scalar() is None:
                await conn.exec_driver_sql(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    finally:
        await engine.dispose()


async def _create_schema() -> None:
    # スキーマはモデル定義から作る。マイグレーションの検証は別（alembic upgrade head
    # を開発フローで踏む）。ここでの関心はテーブルがあることだけ。
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    # 同期フィクスチャの中で asyncio.run する：pytest-asyncio のループスコープに
    # 縛られず、セッション中1回だけ走らせるため。
    asyncio.run(_create_database_if_missing())
    asyncio.run(_create_schema())
    yield


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """外側トランザクションの上に乗るセッション。テスト終了時に全部消える。"""
    engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """DB につながっていないクライアント（配線確認用）ではなく、テスト用セッション
    を注入したクライアント。``get_session`` の commit 境界は本番と同じにしておく。
    """
    app = create_app()

    async def _override() -> AsyncIterator[AsyncSession]:
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def create_user(
    db_session: AsyncSession,
    email: str,
    *,
    display_name: str = "テストユーザー",
    is_demo: bool = False,
) -> User:
    """``users`` を直接作る。CLI（§9-0）はテストでは使わない（design.md §13）。"""
    user = User(
        email=email,
        password_hash=hash_password(PASSWORD),
        display_name=display_name,
        is_demo=is_demo,
    )
    db_session.add(user)
    await db_session.flush()
    return user


async def login(client: AsyncClient, email: str) -> AsyncClient:
    """``POST /auth/login`` を1回叩き、以降の呼び出しに Authorization を付ける。"""
    response = await client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    client.headers["Authorization"] = f"Bearer {response.json()['token']}"
    return client


@pytest.fixture
async def owner(db_session: AsyncSession) -> User:
    return await create_user(db_session, "owner@example.com", display_name="オーナー")


@pytest.fixture
async def owner_client(client: AsyncClient, owner: User) -> AsyncClient:
    return await login(client, owner.email)
