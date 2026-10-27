"""Qiita トークンの登録・差し替え・削除のテスト（C5・publishing design.md §10-1・§10-2）。"""

import logging

import pytest
from app.channels.capabilities import ChannelCode
from app.core.crypto import TokenCipher
from app.core.exceptions import (
    ForbiddenError,
    InvalidQiitaTokenError,
    QiitaTokenInvalidError,
    QiitaTokenMissingError,
    QiitaUnavailableAppError,
)
from app.modules.publishing.ports import QiitaAuthError, QiitaUnavailableError
from cryptography.fernet import Fernet

from tests.modules.publishing.conftest import TEST_KEY, Accounts

TOKEN = "qiita-token-aaaaaaaaaaaaaaaa"


async def test_register_checks_with_qiita_and_stores_only_ciphertext(accounts: Accounts) -> None:
    account = await accounts.service.register_qiita(accounts.user, TOKEN)

    assert accounts.qiita.tokens_seen == [TOKEN]
    assert account.external_user_id == "t_mando_"
    assert TOKEN.encode() not in account.encrypted_token
    assert await accounts.service.qiita_token_for(accounts.user) == TOKEN


async def test_registering_again_replaces_the_token(accounts: Accounts) -> None:
    await accounts.service.register_qiita(accounts.user, TOKEN)
    accounts.qiita.user_name = "renamed"

    await accounts.service.register_qiita(accounts.user, "second-token")

    assert await accounts.service.qiita_token_for(accounts.user) == "second-token"
    account = await accounts.service.get_qiita(accounts.user)
    assert account is not None and account.external_user_id == "renamed"


async def test_a_token_qiita_rejects_is_not_stored(accounts: Accounts) -> None:
    accounts.qiita.fail_with = QiitaAuthError("Unauthorized")

    with pytest.raises(InvalidQiitaTokenError):
        await accounts.service.register_qiita(accounts.user, TOKEN)

    assert await accounts.service.get_qiita(accounts.user) is None


async def test_qiita_outage_during_registration_is_502(accounts: Accounts) -> None:
    accounts.qiita.fail_with = QiitaUnavailableError("down")

    with pytest.raises(QiitaUnavailableAppError):
        await accounts.service.register_qiita(accounts.user, TOKEN)


async def test_tokens_are_per_user(accounts: Accounts) -> None:
    await accounts.service.register_qiita(accounts.user, TOKEN)

    assert await accounts.service.get_qiita(accounts.other) is None
    with pytest.raises(QiitaTokenMissingError):
        await accounts.service.qiita_token_for(accounts.other)


async def test_delete_removes_the_token(accounts: Accounts) -> None:
    await accounts.service.register_qiita(accounts.user, TOKEN)

    await accounts.service.delete_qiita(accounts.user)
    await accounts.service.delete_qiita(accounts.user)  # 2回目も 204 相当

    assert await accounts.service.get_qiita(accounts.user) is None


async def test_demo_cannot_register_or_delete(accounts: Accounts) -> None:
    with pytest.raises(ForbiddenError):
        await accounts.service.register_qiita(accounts.demo, TOKEN)
    with pytest.raises(ForbiddenError):
        await accounts.service.delete_qiita(accounts.demo)
    assert accounts.qiita.tokens_seen == []
    assert await accounts.service.get_qiita(accounts.demo) is None


async def test_a_token_encrypted_with_a_removed_key_asks_for_re_registration(
    accounts: Accounts,
) -> None:
    await accounts.repo.upsert(
        user_id=accounts.user.user_id,
        channel=ChannelCode.QIITA,
        encrypted_token=TokenCipher([Fernet.generate_key().decode()]).encrypt(TOKEN),
        external_user_id="t_mando_",
    )

    with pytest.raises(QiitaTokenInvalidError):
        await accounts.service.qiita_token_for(accounts.user)


async def test_a_token_under_an_old_key_is_re_encrypted_on_use(accounts: Accounts) -> None:
    old_key = Fernet.generate_key().decode()
    await accounts.repo.upsert(
        user_id=accounts.user.user_id,
        channel=ChannelCode.QIITA,
        encrypted_token=TokenCipher([old_key]).encrypt(TOKEN),
        external_user_id="t_mando_",
    )
    rotated = type(accounts.service)(
        accounts.repo, accounts.qiita, TokenCipher([TEST_KEY, old_key])
    )

    assert await rotated.qiita_token_for(accounts.user) == TOKEN

    account = await accounts.service.get_qiita(accounts.user)
    assert account is not None
    # 先頭の鍵だけで読めるようになっている。
    assert accounts.cipher.decrypt(account.encrypted_token).stale is False


async def test_the_token_never_reaches_the_logs(
    accounts: Accounts, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    accounts.qiita.fail_with = QiitaAuthError("Unauthorized")
    with pytest.raises(InvalidQiitaTokenError):
        await accounts.service.register_qiita(accounts.user, TOKEN)
    accounts.qiita.fail_with = None
    await accounts.service.register_qiita(accounts.user, TOKEN)
    await accounts.service.qiita_token_for(accounts.user)

    assert TOKEN not in caplog.text
