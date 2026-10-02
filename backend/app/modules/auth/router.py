"""auth モジュールの HTTP コントローラ ── DTO の検証とステータスコードのみ。

業務判断はここに置かない。それは service.py の責務（ADR-0009）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.modules.auth import schemas
from app.modules.auth.deps import CurrentActor, get_auth_service, get_current_token
from app.modules.auth.service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])

ServiceDep = Annotated[AuthService, Depends(get_auth_service)]


@router.post("/login", response_model=schemas.LoginResponse)
async def login(body: schemas.LoginRequest, service: ServiceDep) -> schemas.LoginResponse:
    result = await service.login(body.email, body.password)
    return schemas.LoginResponse(
        token=result.token,
        expires_at=result.expires_at,
        user=schemas.UserOut.model_validate(result.user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    token: Annotated[str, Depends(get_current_token)],
    service: ServiceDep,
) -> None:
    # セッションの解決（CurrentActor）は要求しない。失効させたいトークンそのものが
    # 資格情報なので、期限切れ・失効済みでも 204 を返す（service.logout は冪等）。
    # ここで 401 にすると、期限切れのタブからログアウトした人が失敗したように見える。
    await service.logout(token)


@router.get("/me", response_model=schemas.MeResponse)
async def me(actor: CurrentActor, service: ServiceDep) -> schemas.MeResponse:
    user = await service.get_user(actor.user_id)
    return schemas.MeResponse.model_validate(user)
