"""HTTP controller for the auth module — DTO validation and status codes only.

No business decisions here; those live in service.py (ADR-0009).
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
    _actor: CurrentActor,
    token: Annotated[str, Depends(get_current_token)],
    service: ServiceDep,
) -> None:
    await service.logout(token)


@router.get("/me", response_model=schemas.MeResponse)
async def me(actor: CurrentActor, service: ServiceDep) -> schemas.MeResponse:
    user = await service.get_user(actor.user_id)
    return schemas.MeResponse.model_validate(user)
