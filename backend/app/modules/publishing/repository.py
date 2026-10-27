"""publishing モジュールの DB アクセス（publishing design.md §3）。"""

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.channels.capabilities import ChannelCode
from app.modules.publishing.models import ChannelAccount


class ChannelAccountRepository:
    """ユーザー×チャネルのトークン。読み書きは常に ``user_id`` で絞る（design.md §5）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int, channel: ChannelCode) -> ChannelAccount | None:
        result = await self._session.execute(
            select(ChannelAccount).where(
                ChannelAccount.user_id == user_id, ChannelAccount.channel == channel.value
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self, *, user_id: int, channel: ChannelCode, encrypted_token: bytes, external_user_id: str
    ) -> ChannelAccount:
        """登録と差し替えを1文で。同じ人が2タブで同時に登録しても UNIQUE で落ちない。"""
        values = insert(ChannelAccount).values(
            user_id=user_id,
            channel=channel.value,
            encrypted_token=encrypted_token,
            external_user_id=external_user_id,
        )
        stmt = values.on_conflict_do_update(
            constraint="uq_channel_accounts_user_channel",
            set_={
                "encrypted_token": values.excluded.encrypted_token,
                "external_user_id": values.excluded.external_user_id,
                "updated_at": func.now(),
            },
        ).returning(ChannelAccount)
        # 同じセッションに古い行が載っていても、返ってきた値で上書きする。
        result = await self._session.scalars(stmt, execution_options={"populate_existing": True})
        return result.one()

    async def replace_token(self, account: ChannelAccount, encrypted_token: bytes) -> None:
        """古い鍵の暗号文を先頭の鍵で暗号化し直す（design.md §10-1）。"""
        account.encrypted_token = encrypted_token
        await self._session.flush()

    async def delete(self, user_id: int, channel: ChannelCode) -> None:
        await self._session.execute(
            delete(ChannelAccount).where(
                ChannelAccount.user_id == user_id, ChannelAccount.channel == channel.value
            )
        )
