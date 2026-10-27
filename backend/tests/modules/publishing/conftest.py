"""publishing の実 DB テスト用の組み立て（publishing design.md §15）。

Repository は本物、外部 API のポートは fake、暗号化は固定鍵の本物の ``TokenCipher``。
"""

from dataclasses import dataclass

import pytest
from app.core.authorization import Actor
from app.core.crypto import TokenCipher
from app.modules.publishing.repository import ChannelAccountRepository
from app.modules.publishing.service import AccountService
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import create_user
from tests.modules.publishing.fakes import FakeQiita

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
