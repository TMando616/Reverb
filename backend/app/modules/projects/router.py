"""HTTP controller for the projects module — DTO validation and status codes only.

No business decisions here; those live in service.py (ADR-0009). Authorization
runs inside the services, not as a router guard, so non-HTTP callers get the
same checks (design.md §5-2, F5).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.authorization import Role
from app.modules.auth.deps import CurrentActor
from app.modules.projects import schemas
from app.modules.projects.deps import (
    OptionalActor,
    get_invitation_service,
    get_member_service,
    get_project_service,
)
from app.modules.projects.service import (
    InvitationService,
    MemberService,
    ProjectService,
    ProjectWithRole,
)

router = APIRouter(prefix="/projects", tags=["projects"])
invitations_router = APIRouter(prefix="/invitations", tags=["invitations"])

ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
MemberServiceDep = Annotated[MemberService, Depends(get_member_service)]
InvitationServiceDep = Annotated[InvitationService, Depends(get_invitation_service)]


def _project_out(row: ProjectWithRole) -> schemas.ProjectOut:
    return schemas.ProjectOut(
        id=row.project.id,
        name=row.project.name,
        role=row.role,
        created_at=row.project.created_at,
    )


@router.get("", response_model=list[schemas.ProjectOut])
async def list_projects(
    actor: CurrentActor, service: ProjectServiceDep
) -> list[schemas.ProjectOut]:
    return [_project_out(row) for row in await service.list_mine(actor)]


@router.post("", response_model=schemas.ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: schemas.ProjectCreateRequest, actor: CurrentActor, service: ProjectServiceDep
) -> schemas.ProjectOut:
    return _project_out(await service.create(actor, name=body.name))


@router.get("/{project_id}", response_model=schemas.ProjectOut)
async def get_project(
    project_id: int, actor: CurrentActor, service: ProjectServiceDep
) -> schemas.ProjectOut:
    return _project_out(await service.get(actor, project_id))


@router.post(
    "/{project_id}/invitations",
    response_model=schemas.InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    project_id: int,
    body: schemas.InvitationCreateRequest,
    actor: CurrentActor,
    service: MemberServiceDep,
) -> schemas.InvitationOut:
    created = await service.invite(actor, project_id, role=body.role, email=body.email)
    return schemas.InvitationOut(
        accept_path=created.accept_path,
        role=Role(created.invitation.role),
        email=created.invitation.email,
        expires_at=created.invitation.expires_at,
    )


@router.get("/{project_id}/members", response_model=list[schemas.MemberOut])
async def list_members(
    project_id: int, actor: CurrentActor, service: MemberServiceDep
) -> list[schemas.MemberOut]:
    members = await service.list_members(actor, project_id)
    return [schemas.MemberOut.model_validate(m) for m in members]


@router.patch("/{project_id}/members/{user_id}", response_model=schemas.MemberRoleOut)
async def change_member_role(
    project_id: int,
    user_id: int,
    body: schemas.MemberRoleUpdateRequest,
    actor: CurrentActor,
    service: MemberServiceDep,
) -> schemas.MemberRoleOut:
    member = await service.change_role(actor, project_id, user_id, role=body.role)
    return schemas.MemberRoleOut.model_validate(member)


@router.delete("/{project_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    project_id: int, user_id: int, actor: CurrentActor, service: MemberServiceDep
) -> None:
    await service.remove(actor, project_id, user_id)


@invitations_router.post("/{token}/accept", response_model=schemas.InvitationAcceptOut)
async def accept_invitation(
    token: str,
    body: schemas.InvitationAcceptRequest,
    actor: OptionalActor,
    service: InvitationServiceDep,
) -> schemas.InvitationAcceptOut:
    result = await service.accept(
        actor, token, display_name=body.display_name, password=body.password
    )
    return schemas.InvitationAcceptOut(project_id=result.project_id, role=result.role)
