"""HTTP を経由しない管理コマンド（design.md §9-0）。

自己登録は存在せず（F2）、招待できるのは企画の owner だけ ── つまりこの入口
が無いと誰もログインできない。bootstrap の入口が循環している。これは運用上の
入口であって API ではない：「最初のユーザーを作り、最初のメンバーシップを
払い出す」ところで止め、それ以上機能を足さない（design.md §9-0）。

コマンドは SQL を直書きせず ``UserRepository`` / ``InvitationService`` を経由する。
パスワードハッシュ化と招待の規則を二重実装しないためである。リクエスト経路と
異なり ``get_session`` の dependency はここに無いので、このモジュール自身が
``async_session()`` を開き、唯一の ``commit()`` を持つ。

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
    """操作者側のミス（不明な id、メールアドレスの重複、プロンプト用の tty が無い等）。

    1行のメッセージと非ゼロの終了コードで報告する。トレースバックは出さない。
    """


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    display_name: str,
    is_demo: bool,
    generate: bool,
) -> None:
    """ログイン可能なユーザーを作成する。bootstrap の owner も demo アカウントも
    ここから作る（design.md §9-0）。
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
        # 1回だけ表示し、平文で保存はしない。再表示は不可能。
        print(f"password: {password}")


async def _add_member(session: AsyncSession, *, project_id: int, user_id: int, role: Role) -> None:
    """招待を経由せず、メンバーシップを直接付与する。

    招待受諾の運用側の対応版：受諾は書き込みで demo アカウントは読み取り専用
    なので、demo が企画に参加する経路はこちらになる（design.md §5-3、§9-0）。
    """
    projects = ProjectRepository(session)
    users = UserRepository(session)
    members = ProjectMemberRepository(session)

    if await projects.get(project_id) is None:
        raise CommandError(f"project #{project_id} does not exist")
    if await users.get(user_id) is None:
        raise CommandError(f"user #{user_id} does not exist")

    # `add` は ON CONFLICT DO NOTHING（design.md §9-2）なので、既存メンバーは
    # 旧ロールが黙って残る。成功として報告せず、その旨をエラーにする。
    existing = await members.role_of(user_id, project_id)
    if existing is not None:
        raise CommandError(
            f"user #{user_id} is already {existing.value} in project #{project_id}; "
            "change the role through the API instead"
        )

    await members.add(project_id=project_id, user_id=user_id, role=role)
    print(f"added user #{user_id} to project #{project_id} as {role.value}")


async def _accept_invitation(session: AsyncSession, *, token: str, email: str) -> None:
    """既存ユーザーとして、ターミナルから招待を受諾する。

    受諾時の新規登録はブラウザの役割（design.md §9-1）なので、ここではアカウントが
    既に存在している必要がある。実際の ``InvitationService`` を呼ぶ ── CLI にも
    招待の規則を回避する近道は作らない。
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
    """``(password, was_generated)`` を返す。

    argv からは受け取らないので、シェル履歴に残らない（design.md §9-0）：
    プロンプトで入力するか、ここで生成する。
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
    """1コマンド＝1セッション＝1トランザクション。``get_session`` と同じ形にする
    （design.md §4-4）。Service は flush だけ行い、唯一の ``commit()`` はここにある。
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
        # 操作者側のミスとドメイン上の拒否（demo アカウントの受諾試行など）は
        # メッセージとして扱い、トレースバックにはしない。
        raise SystemExit(f"error: {exc}") from exc


if __name__ == "__main__":
    main()
