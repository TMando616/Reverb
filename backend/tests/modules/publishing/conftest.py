"""publishing の実 DB テスト用の組み立て（publishing design.md §15）。

Repository は本物、外部 API のポートは fake、暗号化は固定鍵の本物の ``TokenCipher``。
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

import pytest
from app.core.authorization import Actor, ProjectAuthorizer
from app.core.crypto import TokenCipher
from app.modules.contents.models import Content
from app.modules.contents.service import ContentService
from app.modules.projects.repository import ProjectMemberRepository
from app.modules.publishing.ports import NoopDispatcher
from app.modules.publishing.repository import (
    ChannelAccountRepository,
    ChannelDraftRepository,
    ConversionJobRepository,
    ConversionProfileRepository,
)
from app.modules.publishing.service import AccountService, ConversionService
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user

# world フィクスチャを contents から借りる（conftest に import すると pytest が登録する）。
from tests.modules.contents.conftest import World, world  # noqa: F401
from tests.modules.publishing.fakes import FakeConverter, FakeQiita

TEST_KEY = Fernet.generate_key().decode()


@dataclass(frozen=True)
class Accounts:
    service: AccountService
    qiita: FakeQiita
    cipher: TokenCipher
    repo: ChannelAccountRepository
    user: Actor
    other: Actor
    demo: Actor


@pytest.fixture
async def accounts(db_session: AsyncSession) -> Accounts:
    user = await create_user(db_session, "user@example.com")
    other = await create_user(db_session, "other@example.com")
    demo = await create_user(db_session, "demo@example.com", is_demo=True)
    qiita = FakeQiita()
    cipher = TokenCipher([TEST_KEY])
    repo = ChannelAccountRepository(db_session)
    return Accounts(
        service=AccountService(repo, qiita, cipher),
        qiita=qiita,
        cipher=cipher,
        repo=repo,
        user=Actor(user_id=user.id, is_demo=False),
        other=Actor(user_id=other.id, is_demo=False),
        demo=Actor(user_id=demo.id, is_demo=True),
    )


@dataclass(frozen=True)
class Publishing:
    world: World
    conversions: ConversionService
    converter: FakeConverter
    session: AsyncSession

    @property
    def contents(self) -> ContentService:
        return self.world.contents

    async def content(self, title: str = "ECS の話", body: str = "タスク定義でハマった") -> Content:
        return await self.contents.create(
            self.world.owner, self.world.project, title=title, body_md=body
        )

    def sessions(self) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
        """ワーカーの ``run_once`` に渡すセッション工場。テストの外側トランザクションに乗せる
        （commit は SAVEPOINT の解放になる・tests/conftest.py）。
        """

        @asynccontextmanager
        async def _factory() -> AsyncIterator[AsyncSession]:
            yield self.session

        return _factory


@pytest.fixture
async def publishing(world: World, db_session: AsyncSession) -> Publishing:  # noqa: F811
    authz = ProjectAuthorizer(ProjectMemberRepository(db_session))
    return Publishing(
        world=world,
        conversions=ConversionService(
            contents=world.contents,
            authz=authz,
            profiles=ConversionProfileRepository(db_session),
            jobs=ConversionJobRepository(db_session),
            drafts=ChannelDraftRepository(db_session),
            dispatcher=NoopDispatcher(),
            model="claude-opus-5-5",
        ),
        converter=FakeConverter(),
        session=db_session,
    )
