"""publishing モジュールの HTTP コントローラ ── DTO の検証とステータスコードのみ。

業務判断はここに置かない（ADR-0009）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.channels.capabilities import CAPABILITIES, ChannelCode
from app.modules.auth.deps import CurrentActor
from app.modules.publishing import schemas
from app.modules.publishing.deps import (
    get_account_service,
    get_conversion_service,
    get_draft_service,
)
from app.modules.publishing.service import AccountService, ConversionService, DraftService

# 企画の外（ユーザー単位）なので /projects の下に置かない（design.md §6）。
accounts_router = APIRouter(prefix="/me/accounts", tags=["accounts"])

channels_router = APIRouter(prefix="/channels", tags=["channels"])
content_channels_router = APIRouter(
    prefix="/projects/{project_id}/contents/{content_id}", tags=["publishing"]
)

AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
ConversionServiceDep = Annotated[ConversionService, Depends(get_conversion_service)]
DraftServiceDep = Annotated[DraftService, Depends(get_draft_service)]


@channels_router.get("", response_model=list[schemas.ChannelOut])
async def list_channels(_actor: CurrentActor) -> list[schemas.ChannelOut]:
    return [
        schemas.ChannelOut(
            code=code,
            label=caps.label,
            publish=caps.publish,
            metrics=caps.metrics,
            format=caps.format,
            max_length=caps.max_length,
        )
        for code, caps in CAPABILITIES.items()
    ]


@content_channels_router.post(
    "/channels/{channel}/conversions",
    response_model=schemas.ConversionJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_conversion(
    project_id: int,
    content_id: int,
    channel: ChannelCode,
    actor: CurrentActor,
    service: ConversionServiceDep,
) -> schemas.ConversionJobOut:
    job = await service.request(actor, project_id, content_id, channel)
    return schemas.ConversionJobOut.from_job(job)


@content_channels_router.get("/conversions", response_model=list[schemas.ConversionJobSummary])
async def list_conversions(
    project_id: int, content_id: int, actor: CurrentActor, service: ConversionServiceDep
) -> list[schemas.ConversionJobSummary]:
    jobs = await service.list_jobs(actor, project_id, content_id)
    return [schemas.ConversionJobSummary.model_validate(job) for job in jobs]


@content_channels_router.get("/conversions/{job_id}", response_model=schemas.ConversionJobOut)
async def get_conversion(
    project_id: int,
    content_id: int,
    job_id: int,
    actor: CurrentActor,
    service: ConversionServiceDep,
) -> schemas.ConversionJobOut:
    return schemas.ConversionJobOut.from_job(
        await service.get_job(actor, project_id, content_id, job_id)
    )


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


@content_channels_router.get("/channels/{channel}", response_model=schemas.ChannelViewOut)
async def get_channel_view(
    project_id: int,
    content_id: int,
    channel: ChannelCode,
    actor: CurrentActor,
    service: DraftServiceDep,
) -> schemas.ChannelViewOut:
    view = await service.view(actor, project_id, content_id, channel)
    return schemas.ChannelViewOut.from_view(view)


@content_channels_router.put("/channels/{channel}/draft", response_model=schemas.ChannelDraftOut)
async def save_draft(
    project_id: int,
    content_id: int,
    channel: ChannelCode,
    body: schemas.DraftSaveRequest,
    actor: CurrentActor,
    service: DraftServiceDep,
) -> schemas.ChannelDraftOut:
    draft = await service.save(
        actor,
        project_id,
        content_id,
        channel,
        title=body.title,
        body=body.body,
        tags=list(dict.fromkeys(body.tags)),
        expected_version=body.expected_version,
    )
    return schemas.ChannelDraftOut.from_draft(draft)


@content_channels_router.post(
    "/channels/{channel}/draft/apply", response_model=schemas.ChannelDraftOut
)
async def apply_pending_conversion(
    project_id: int,
    content_id: int,
    channel: ChannelCode,
    body: schemas.DraftApplyRequest,
    actor: CurrentActor,
    service: DraftServiceDep,
) -> schemas.ChannelDraftOut:
    draft = await service.apply_pending(
        actor,
        project_id,
        content_id,
        channel,
        job_id=body.job_id,
        expected_version=body.expected_version,
    )
    return schemas.ChannelDraftOut.from_draft(draft)
