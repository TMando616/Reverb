"""publishing モジュールの dependency 組み立て（publishing design.md §2）。

ポートに具体実装（Qiita API・暗号化）を差し込むのはここだけ。テストは
``app.dependency_overrides`` でこれらの関数を差し替える。
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.qiita import QiitaClient
from app.core.authorization import ProjectAuthorizer
from app.core.config import get_settings
from app.core.crypto import TokenCipher
from app.core.db import get_session
from app.llm.converter import ClaudeConverter, build_client
from app.modules.contents.deps import get_content_service
from app.modules.projects.repository import ProjectMemberRepository
from app.modules.publishing.ports import Converter, NoopDispatcher, QiitaGateway, TokenCipherPort
from app.modules.publishing.repository import (
    ChannelAccountRepository,
    ChannelDraftRepository,
    ConversionJobRepository,
    ConversionProfileRepository,
)
from app.modules.publishing.service import AccountService, ConversionService

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@lru_cache
def _token_cipher() -> TokenCipher:
    return TokenCipher(get_settings().token_encryption_key_list)


def get_token_cipher() -> TokenCipherPort:
    return _token_cipher()


def get_qiita_gateway() -> QiitaGateway:
    return QiitaClient()


def get_account_service(
    session: SessionDep,
    qiita: Annotated[QiitaGateway, Depends(get_qiita_gateway)],
    cipher: Annotated[TokenCipherPort, Depends(get_token_cipher)],
) -> AccountService:
    return AccountService(ChannelAccountRepository(session), qiita, cipher)


@lru_cache
def get_converter() -> Converter:
    # クライアントは接続プールを持つので、プロセスで1つを使い回す。
    settings = get_settings()
    return ClaudeConverter(
        build_client(), model=settings.conversion_model, effort=settings.conversion_effort
    )


def build_conversion_service(session: AsyncSession) -> ConversionService:
    """HTTP（Depends）とワーカーの両方から使う組み立て。ワーカーは自分のセッションを渡す。"""
    return ConversionService(
        contents=get_content_service(session),
        authz=ProjectAuthorizer(ProjectMemberRepository(session)),
        profiles=ConversionProfileRepository(session),
        jobs=ConversionJobRepository(session),
        drafts=ChannelDraftRepository(session),
        dispatcher=NoopDispatcher(),
        model=get_settings().conversion_model,
    )


def get_conversion_service(session: SessionDep) -> ConversionService:
    return build_conversion_service(session)
