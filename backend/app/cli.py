"""Management commands that bypass HTTP (design.md §9-0).

Self-registration does not exist (F2) and only a project owner can invite, so
without this entry point nobody can ever sign in — the bootstrap is circular.
This is the operational way in, not an API: it stays at "create the first user
and hand out the first membership" and grows no further (design.md §9-0).

Commands go through ``UserRepository`` / ``InvitationService`` rather than raw
SQL so password hashing and the invitation rules are never implemented twice.
Unlike the request path there is no ``get_session`` dependency here, so this
module opens ``async_session()`` itself and owns the single ``commit()``.

    docker compose exec backend python -m app.cli create-user \
        --email owner@example.com --display-name まんどぅ
    docker compose exec backend python -m app.cli create-user \
        --email demo@example.com --display-name デモ --demo
    docker compose exec backend python -m app.cli add-member \
        --project 1 --user 2 --role reviewer
    docker compose exec backend python -m app.cli accept-invitation \
        --token <token> --email owner@example.com
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import secrets
import sys

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import Actor, Role
from app.core.db import async_session, engine
from app.core.exceptions import AppError
from app.core.security import hash_password
from app.modules.auth.repository import UserRepository
from app.modules.projects.repository import (
    InvitationRepository,
    ProjectMemberRepository,
    ProjectRepository,
)
from app.modules.projects.service import InvitationService

GENERATED_PASSWORD_BYTES = 16


class CommandError(Exception):
    """An operator mistake (unknown id, duplicate email, no tty for the prompt).

    Reported as a one-line message and a non-zero exit, never a traceback.
    """


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    display_name: str,
    is_demo: bool,
    generate: bool,
) -> None:
    """Create a sign-in-able user. The bootstrap owner and the demo account
    both come from here (design.md §9-0).
    """
    users = UserRepository(session)
    if await users.get_by_email(email) is not None:
        raise CommandError(f"a user already exists for {email}")

    password, was_generated = _resolve_password(generate)
    user = await users.create(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        is_demo=is_demo,
    )
    print(f"created user #{user.id}  {email}  demo={is_demo}")
    if was_generated:
        # Printed once and never stored in the clear; it is not recoverable.
        print(f"password: {password}")


async def _add_member(session: AsyncSession, *, project_id: int, user_id: int, role: Role) -> None:
    """Grant a membership directly, without an invitation.

    The ops-side counterpart to invitation acceptance: it is how the demo
    account joins a project, since accepting is a write and demo accounts are
    read-only (design.md §5-3, §9-0).
    """
    projects = ProjectRepository(session)
    users = UserRepository(session)
    members = ProjectMemberRepository(session)

    if await projects.get(project_id) is None:
        raise CommandError(f"project #{project_id} does not exist")
    if await users.get(user_id) is None:
        raise CommandError(f"user #{user_id} does not exist")

    # `add` is ON CONFLICT DO NOTHING (design.md §9-2), so an existing member
    # would silently keep their old role. Say so instead of reporting success.
    existing = await members.role_of(user_id, project_id)
    if existing is not None:
        raise CommandError(
            f"user #{user_id} is already {existing.value} in project #{project_id}; "
            "change the role through the API instead"
        )

    await members.add(project_id=project_id, user_id=user_id, role=role)
    print(f"added user #{user_id} to project #{project_id} as {role.value}")


async def _accept_invitation(session: AsyncSession, *, token: str, email: str) -> None:
    """Accept an invitation from the terminal, as an existing user.

    Registration-on-accept is the browser's job (design.md §9-1), so the
    account must already exist here. Runs the real ``InvitationService`` — the
    CLI gets no shortcut past the invitation rules.
    """
    users = UserRepository(session)
    user = await users.get_by_email(email)
    if user is None:
        raise CommandError(f"no user for {email}; run create-user first")

    service = InvitationService(
        invitations=InvitationRepository(session),
        members=ProjectMemberRepository(session),
        users=users,
    )
    result = await service.accept(
        Actor(user_id=user.id, is_demo=user.is_demo),
        token,
        display_name=None,
        password=None,
    )
    print(f"user #{user.id} joined project #{result.project_id} as {result.role.value}")


def _resolve_password(generate: bool) -> tuple[str, bool]:
    """Return ``(password, was_generated)``.

    Never taken from argv, so it does not land in the shell history
    (design.md §9-0): either typed at a prompt or generated here.
    """
    if generate:
        return secrets.token_urlsafe(GENERATED_PASSWORD_BYTES), True
    if not sys.stdin.isatty():
        raise CommandError("no tty for the password prompt; pass --generate-password")
    password = getpass.getpass("password: ")
    if not password:
        raise CommandError("password must not be empty")
    if password != getpass.getpass("password (again): "):
        raise CommandError("passwords did not match")
    return password, False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="Reverb bootstrap commands (design.md §9-0)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create_user = sub.add_parser("create-user", help="create a sign-in-able user")
    create_user.add_argument("--email", required=True)
    create_user.add_argument("--display-name", required=True)
    create_user.add_argument("--demo", action="store_true", help="read-only demo account (is_demo)")
    create_user.add_argument(
        "--generate-password",
        action="store_true",
        help="generate the password and print it once instead of prompting",
    )

    add_member = sub.add_parser("add-member", help="grant a membership directly (no invitation)")
    add_member.add_argument("--project", required=True, type=int, help="project id")
    add_member.add_argument("--user", required=True, type=int, help="user id")
    add_member.add_argument("--role", required=True, choices=[role.value for role in Role])

    accept = sub.add_parser("accept-invitation", help="accept an invitation as an existing user")
    accept.add_argument("--token", required=True, help="raw token from the accept URL")
    accept.add_argument("--email", required=True, help="email of the accepting user")

    return parser


async def _dispatch(session: AsyncSession, args: argparse.Namespace) -> None:
    if args.command == "create-user":
        await _create_user(
            session,
            email=args.email,
            display_name=args.display_name,
            is_demo=args.demo,
            generate=args.generate_password,
        )
    elif args.command == "add-member":
        await _add_member(session, project_id=args.project, user_id=args.user, role=Role(args.role))
    elif args.command == "accept-invitation":
        await _accept_invitation(session, token=args.token, email=args.email)


async def _run(args: argparse.Namespace) -> None:
    """One command == one session == one transaction, mirroring ``get_session``
    (design.md §4-4). Services flush; the only ``commit()`` is here.
    """
    try:
        async with async_session() as session:
            try:
                await _dispatch(session, args)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        await engine.dispose()


def main() -> None:
    args = _build_parser().parse_args()
    try:
        asyncio.run(_run(args))
    except (CommandError, AppError) as exc:
        # Operator errors and domain refusals (e.g. a demo account trying to
        # accept) are messages, not tracebacks.
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    main()
