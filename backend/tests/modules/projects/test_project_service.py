"""Unit tests for ``ProjectService`` (design.md §5-2 / §5-3, tasks.md §3.8)."""

import pytest
from app.core.authorization import Actor, ProjectAuthorizer, Role
from app.core.exceptions import ForbiddenError, NotFoundError
from app.modules.projects.service import ProjectService

from tests.modules.projects.fakes import FakeProjectMemberRepository, FakeProjectRepository


def _service(
    projects: FakeProjectRepository, members: FakeProjectMemberRepository
) -> ProjectService:
    return ProjectService(projects, members, ProjectAuthorizer(members))  # type: ignore[arg-type]


async def test_demo_cannot_create_a_project() -> None:
    svc = _service(FakeProjectRepository(), FakeProjectMemberRepository())
    with pytest.raises(ForbiddenError):
        await svc.create(Actor(user_id=1, is_demo=True), name="Reverb")


async def test_create_enrols_the_creator_as_owner() -> None:
    projects = FakeProjectRepository()
    members = FakeProjectMemberRepository()
    svc = _service(projects, members)

    result = await svc.create(Actor(user_id=7, is_demo=False), name="Reverb")

    assert result.role is Role.OWNER
    assert await members.role_of(7, result.project.id) is Role.OWNER


async def test_get_hides_a_project_from_a_non_member_as_404() -> None:
    svc = _service(FakeProjectRepository(), FakeProjectMemberRepository())
    with pytest.raises(NotFoundError):
        await svc.get(Actor(user_id=1, is_demo=False), 99)


async def test_get_returns_the_members_own_role() -> None:
    projects = FakeProjectRepository()
    project = await projects.create(name="Reverb", created_by=1)
    members = FakeProjectMemberRepository(members=[(project.id, 1, Role.EDITOR)])
    svc = _service(projects, members)

    result = await svc.get(Actor(user_id=1, is_demo=False), project.id)

    assert result.role is Role.EDITOR
    assert result.project.id == project.id


async def test_list_mine_returns_each_project_with_a_role() -> None:
    projects = FakeProjectRepository()
    members = FakeProjectMemberRepository()
    p1 = await projects.create(name="A", created_by=1)
    p2 = await projects.create(name="B", created_by=2)
    projects.seed_membership(1, p1, Role.OWNER)
    projects.seed_membership(1, p2, Role.REVIEWER)
    svc = _service(projects, members)

    rows = await svc.list_mine(Actor(user_id=1, is_demo=False))

    assert {(r.project.name, r.role) for r in rows} == {("A", Role.OWNER), ("B", Role.REVIEWER)}


async def test_demo_member_may_still_read_a_project() -> None:
    # Demo is clamped to VIEW_ONLY, not blocked from reads (design.md §5-2).
    projects = FakeProjectRepository()
    project = await projects.create(name="Reverb", created_by=1)
    members = FakeProjectMemberRepository(members=[(project.id, 1, Role.OWNER)])
    svc = _service(projects, members)

    result = await svc.get(Actor(user_id=1, is_demo=True), project.id)

    assert result.project.id == project.id
