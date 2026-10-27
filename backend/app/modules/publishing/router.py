"""publishing モジュールの HTTP コントローラ ── DTO の検証とステータスコードのみ。

業務判断はここに置かない（ADR-0009）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.modules.auth.deps import CurrentActor
from app.modules.publishing import schemas
from app.modules.publishing.deps import get_account_service
from app.modules.publishing.service import AccountService

# 企画の外（ユーザー単位）なので /projects の下に置かない（design.md §6）。
accounts_router = APIRouter(prefix="/me/accounts", tags=["accounts"])

AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]


@accounts_router.get("/qiita", response_model=schemas.QiitaAccountOut)
async def get_qiita_account(
    actor: CurrentActor, service: AccountServiceDep
) -> schemas.QiitaAccountOut:
    account = await service.get_qiita(actor)
    if account is None:
        return schemas.QiitaAccountOut(registered=False)
    return schemas.QiitaAccountOut(registered=True, external_user_id=account.external_user_id)


@accounts_router.put("/qiita", response_model=schemas.QiitaAccountOut)
async def register_qiita_account(
    body: schemas.QiitaAccountRegisterRequest, actor: CurrentActor, service: AccountServiceDep
) -> schemas.QiitaAccountOut:
    account = await service.register_qiita(actor, body.token.get_secret_value().strip())
    return schemas.QiitaAccountOut(registered=True, external_user_id=account.external_user_id)


@accounts_router.delete("/qiita", status_code=status.HTTP_204_NO_CONTENT)
async def delete_qiita_account(actor: CurrentActor, service: AccountServiceDep) -> None:
    await service.delete_qiita(actor)
