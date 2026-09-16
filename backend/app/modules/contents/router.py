"""HTTP controller for the contents module — DTO validation and status codes only.

No business decisions here; those live in service.py (ADR-0009). Every path
carries ``project_id`` so a content is only ever reached through its project
(design.md §6-1, F5).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.modules.auth.deps import CurrentActor
from app.modules.contents import schemas
from app.modules.contents.deps import get_content_service
from app.modules.contents.models import ContentStatus
from app.modules.contents.service import ContentService

router = APIRouter(prefix="/projects/{project_id}/contents", tags=["contents"])

ContentServiceDep = Annotated[ContentService, Depends(get_content_service)]


@router.get("", response_model=list[schemas.ContentOut])
async def list_contents(
    project_id: int,
    actor: CurrentActor,
    service: ContentServiceDep,
    # A single-status filter only; tags / keywords belong to content-pipeline (design.md §6-1).
    status: ContentStatus | None = None,
) -> list[schemas.ContentOut]:
    rows = await service.list(actor, project_id, status=status)
    return [schemas.ContentOut.model_validate(row) for row in rows]


@router.post("", response_model=schemas.ContentOut, status_code=status.HTTP_201_CREATED)
async def create_content(
    project_id: int,
    body: schemas.ContentCreateRequest,
    actor: CurrentActor,
    service: ContentServiceDep,
) -> schemas.ContentOut:
    content = await service.create(actor, project_id, title=body.title, body_md=body.body_md)
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
    )
    return schemas.ContentOut.model_validate(content)


@router.delete("/{content_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_content(
    project_id: int, content_id: int, actor: CurrentActor, service: ContentServiceDep
) -> None:
    await service.delete(actor, project_id, content_id)
