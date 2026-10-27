"""publishing の業務ルールと認可（publishing design.md）。

HTTP のことは知らない（``fastapi`` は import しない）。外部 API の具体実装も知らず、
``ports.py`` の Protocol だけを受け取る（``.importlinter`` で強制）。
Service は flush までで、commit は呼び出し側（``get_session`` / ワーカー）が持つ。
"""

import logging

from app.channels.capabilities import ChannelCode
from app.core.authorization import Actor, require_not_demo
from app.core.crypto import TokenUnavailableError
from app.core.exceptions import (
    AppError,
    InvalidQiitaTokenError,
    QiitaItemMissingError,
    QiitaRateLimitedAppError,
    QiitaRejectedPublishError,
    QiitaTokenInvalidError,
    QiitaTokenMissingError,
    QiitaUnavailableAppError,
)
from app.modules.publishing.models import ChannelAccount
from app.modules.publishing.ports import (
    QiitaAuthError,
    QiitaError,
    QiitaGateway,
    QiitaNotFoundError,
    QiitaRateLimitedError,
    QiitaRejectedError,
    TokenCipherPort,
)
from app.modules.publishing.repository import ChannelAccountRepository

logger = logging.getLogger("app.publishing")


def qiita_app_error(exc: QiitaError) -> AppError:
    """Qiita のポート例外を HTTP のエラーコードに写す（design.md §10-5）。"""
    if isinstance(exc, QiitaAuthError):
        return QiitaTokenInvalidError()
    if isinstance(exc, QiitaNotFoundError):
        return QiitaItemMissingError()
    if isinstance(exc, QiitaRejectedError):
        return QiitaRejectedPublishError(str(exc))
    if isinstance(exc, QiitaRateLimitedError):
        return QiitaRateLimitedAppError()
    return QiitaUnavailableAppError()


class AccountService:
    """本人の外部トークンの登録・差し替え・削除（C5・design.md §5・§10-2）。

    企画の認可を通らない。対象は常に ``actor.user_id`` の行で、他人の行を指す引数を持たない。
    demo は書き込みだけ 403（閲覧は自分の「未登録」が見えるだけなので通す）。
    """

    def __init__(
        self, accounts: ChannelAccountRepository, qiita: QiitaGateway, cipher: TokenCipherPort
    ) -> None:
        self._accounts = accounts
        self._qiita = qiita
        self._cipher = cipher

    async def get_qiita(self, actor: Actor) -> ChannelAccount | None:
        return await self._accounts.get(actor.user_id, ChannelCode.QIITA)

    async def register_qiita(self, actor: Actor, token: str) -> ChannelAccount:
        """Qiita に問い合わせて有効なトークンだけを暗号化して保存する。"""
        require_not_demo(actor)
        try:
            external_user_id = await self._qiita.authenticated_user(token)
        except (QiitaAuthError, QiitaRejectedError, QiitaNotFoundError):
            raise InvalidQiitaTokenError() from None
        except QiitaError as exc:
            raise qiita_app_error(exc) from None
        return await self._accounts.upsert(
            user_id=actor.user_id,
            channel=ChannelCode.QIITA,
            encrypted_token=self._cipher.encrypt(token),
            external_user_id=external_user_id,
        )

    async def delete_qiita(self, actor: Actor) -> None:
        require_not_demo(actor)
        await self._accounts.delete(actor.user_id, ChannelCode.QIITA)

    async def qiita_token_for(self, actor: Actor) -> str:
        """公開操作をした本人のトークンを復号して返す。他人のトークンでは投稿しない（§5）。"""
        account = await self._accounts.get(actor.user_id, ChannelCode.QIITA)
        if account is None:
            raise QiitaTokenMissingError()
        try:
            decrypted = self._cipher.decrypt(account.encrypted_token)
        except TokenUnavailableError:
            logger.warning("stored qiita token cannot be decrypted: user=%s", actor.user_id)
            raise QiitaTokenInvalidError() from None
        if decrypted.stale:
            await self._accounts.replace_token(account, self._cipher.encrypt(decrypted.plaintext))
        return decrypted.plaintext
