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
    get_publication_service,
)
from app.modules.publishing.service import (
    AccountService,
    ConversionService,
    DraftService,
    PublicationService,
)

# 企画の外（ユーザー単位）なので /projects の下に置かない（design.md §6）。
accounts_router = APIRouter(prefix="/me/accounts", tags=["accounts"])

channels_router = APIRouter(prefix="/channels", tags=["channels"])
content_channels_router = APIRouter(
    prefix="/projects/{project_id}/contents/{content_id}", tags=["publishing"]
)

AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
ConversionServiceDep = Annotated[ConversionService, Depends(get_conversion_service)]
DraftServiceDep = Annotated[DraftService, Depends(get_draft_service)]
PublicationServiceDep = Annotated[PublicationService, Depends(get_publication_service)]
publications_router = APIRouter(prefix="/projects/{project_id}/publications", tags=["publishing"])


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


# 公開系のパスに qiita を書くのは、M1 で API 公開（auto）できるのが Qiita だけだから。
# 分岐は Service が capabilities を見て行う（design.md §6）。
@content_channels_router.post(
    "/channels/qiita/publish",
    response_model=schemas.PublicationOut,
    status_code=status.HTTP_201_CREATED,
)
async def publish_to_qiita(
    project_id: int,
    content_id: int,
    body: schemas.QiitaPublishRequest,
    actor: CurrentActor,
    service: PublicationServiceDep,
) -> schemas.PublicationOut:
    publication = await service.publish_qiita(
        actor,
        project_id,
        content_id,
        visibility=body.visibility,
        expected_draft_version=body.expected_draft_version,
    )
    return schemas.PublicationOut.model_validate(publication)


@content_channels_router.post("/channels/qiita/push", response_model=schemas.PublicationOut)
async def push_to_qiita(
    project_id: int,
    content_id: int,
    body: schemas.QiitaPushRequest,
    actor: CurrentActor,
    service: PublicationServiceDep,
) -> schemas.PublicationOut:
    publication = await service.push_qiita(
        actor,
        project_id,
        content_id,
        expected_draft_version=body.expected_draft_version,
        visibility=body.visibility,
    )
    return schemas.PublicationOut.model_validate(publication)


@publications_router.get("", response_model=list[schemas.PublishedContentOut])
async def list_publications(
    project_id: int,
    actor: CurrentActor,
    service: PublicationServiceDep,
    content_id: int | None = None,
) -> list[schemas.PublishedContentOut]:
    entries = await service.list_for_project(actor, project_id, content_id=content_id)
    return [schemas.PublishedContentOut.from_entry(entry) for entry in entries]


@publications_router.delete("/{publication_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_publication(
    project_id: int, publication_id: int, actor: CurrentActor, service: PublicationServiceDep
) -> None:
    await service.cancel(actor, project_id, publication_id)
