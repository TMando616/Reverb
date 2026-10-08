"""contents モジュールの HTTP コントローラ ── DTO の検証とステータスコードのみ。

業務判断はここに置かない。それは service.py の責務（ADR-0009）。すべてのパスに
``project_id`` を持たせ、コンテンツは常に企画を経由してのみ到達できるようにする
（design.md §6-1、F5）。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.modules.auth.deps import CurrentActor
from app.modules.contents import schemas
from app.modules.contents.deps import get_content_service, get_tag_service
from app.modules.contents.models import ContentStatus
from app.modules.contents.service import UNSET, ContentService, TagService

router = APIRouter(prefix="/projects/{project_id}/contents", tags=["contents"])
tags_router = APIRouter(prefix="/projects/{project_id}/tags", tags=["tags"])

ContentServiceDep = Annotated[ContentService, Depends(get_content_service)]
TagServiceDep = Annotated[TagService, Depends(get_tag_service)]


@router.get("", response_model=list[schemas.ContentListItem])
async def list_contents(
    project_id: int,
    actor: CurrentActor,
    service: ContentServiceDep,
    # どれも複数指定でき、条件同士は AND（content-pipeline design.md §6-5）。
    # ?tag=1&tag=2 は「1 と 2 を両方持つ」、?status=a&status=b は「a か b」。
    tag: Annotated[list[int], Query()] = [],  # noqa: B006 — FastAPI は既定値を複製して使う
    status: Annotated[list[ContentStatus], Query()] = [],  # noqa: B006
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> list[schemas.ContentListItem]:
    keyword = q.strip() if q else None
    rows = await service.list(actor, project_id, statuses=status, tag_ids=tag, q=keyword or None)
    return [schemas.ContentListItem.model_validate(row) for row in rows]


@router.post("", response_model=schemas.ContentOut, status_code=status.HTTP_201_CREATED)
async def create_content(
    project_id: int,
    body: schemas.ContentCreateRequest,
    actor: CurrentActor,
    service: ContentServiceDep,
) -> schemas.ContentOut:
    content = await service.create(
        actor,
        project_id,
        title=body.title,
        body_md=body.body_md,
        tag_ids=body.tag_ids,
        source_note_path=body.source_note_path,
    )
    return schemas.ContentOut.model_validate(content)


@router.get("/{content_id}", response_model=schemas.ContentOut)
async def get_content(
    project_id: int, content_id: int, actor: CurrentActor, service: ContentServiceDep
) -> schemas.ContentOut:
    return schemas.ContentOut.model_validate(await service.get(actor, project_id, content_id))


@router.patch("/{content_id}", response_model=schemas.ContentOut)
async def update_content(
    project_id: int,
    content_id: int,
    body: schemas.ContentUpdateRequest,
    actor: CurrentActor,
    service: ContentServiceDep,
) -> schemas.ContentOut:
    content = await service.update(
        actor,
        project_id,
        content_id,
        body.expected_version,
        title=body.title,
        body_md=body.body_md,
        # 送られていなければ触らない。null が送られたら消す。
        source_note_path=(
            body.source_note_path if "source_note_path" in body.model_fields_set else UNSET
        ),
    )
    return schemas.ContentOut.model_validate(content)


@router.put("/{content_id}/tags", response_model=schemas.ContentOut)
async def set_content_tags(
    project_id: int,
    content_id: int,
    body: schemas.ContentTagsRequest,
    actor: CurrentActor,
    service: ContentServiceDep,
) -> schemas.ContentOut:
    content = await service.set_tags(actor, project_id, content_id, body.tag_ids)
    return schemas.ContentOut.model_validate(content)


@router.get("/{content_id}/revisions", response_model=list[schemas.RevisionSummaryOut])
async def list_revisions(
    project_id: int,
    content_id: int,
    actor: CurrentActor,
    service: ContentServiceDep,
    before: Annotated[int | None, Query(ge=1)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[schemas.RevisionSummaryOut]:
    rows = await service.list_revisions(actor, project_id, content_id, before=before, limit=limit)
    return [schemas.RevisionSummaryOut.model_validate(row) for row in rows]


@router.get("/{content_id}/revisions/{revision_no}", response_model=schemas.RevisionOut)
async def get_revision(
    project_id: int,
    content_id: int,
    revision_no: int,
    actor: CurrentActor,
    service: ContentServiceDep,
) -> schemas.RevisionOut:
    revision = await service.get_revision(actor, project_id, content_id, revision_no)
    return schemas.RevisionOut.model_validate(revision)


@router.post("/{content_id}/revisions/{revision_no}/restore", response_model=schemas.ContentOut)
async def restore_revision(
    project_id: int,
    content_id: int,
    revision_no: int,
    body: schemas.RevisionRestoreRequest,
    actor: CurrentActor,
    service: ContentServiceDep,
) -> schemas.ContentOut:
    content = await service.restore(
        actor, project_id, content_id, revision_no, body.expected_version
    )
    return schemas.ContentOut.model_validate(content)


@router.post("/{content_id}/transition", response_model=schemas.ContentOut)
async def transition_content(
    project_id: int,
    content_id: int,
    body: schemas.ContentTransitionRequest,
    actor: CurrentActor,
    service: ContentServiceDep,
) -> schemas.ContentOut:
    content = await service.transition(
        actor, project_id, content_id, body.to, body.expected_version
    )
    return schemas.ContentOut.model_validate(content)


@router.delete("/{content_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_content(
    project_id: int, content_id: int, actor: CurrentActor, service: ContentServiceDep
) -> None:
    await service.delete(actor, project_id, content_id)


@tags_router.get("", response_model=list[schemas.TagWithUsageOut])
async def list_tags(
    project_id: int, actor: CurrentActor, service: TagServiceDep
) -> list[schemas.TagWithUsageOut]:
    rows = await service.list(actor, project_id)
    return [
        schemas.TagWithUsageOut(id=tag.id, name=tag.name, content_count=count)
        for tag, count in rows
    ]


@tags_router.post("", response_model=schemas.TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag(
    project_id: int, body: schemas.TagCreateRequest, actor: CurrentActor, service: TagServiceDep
) -> schemas.TagOut:
    return schemas.TagOut.model_validate(await service.create(actor, project_id, name=body.name))


@tags_router.patch("/{tag_id}", response_model=schemas.TagOut)
async def rename_tag(
    project_id: int,
    tag_id: int,
    body: schemas.TagRenameRequest,
    actor: CurrentActor,
    service: TagServiceDep,
) -> schemas.TagOut:
    tag = await service.rename(actor, project_id, tag_id, name=body.name)
    return schemas.TagOut.model_validate(tag)


@tags_router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    project_id: int, tag_id: int, actor: CurrentActor, service: TagServiceDep
) -> None:
    await service.delete(actor, project_id, tag_id)
