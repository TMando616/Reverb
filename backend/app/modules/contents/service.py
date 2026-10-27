"""contents モジュールの業務ルールと認可（コンテンツ CRUD・状態遷移）。

HTTP のことは知らない（``fastapi`` / ``Request`` は import しない）し、
``AsyncSession`` を直接持つこともない ── repository は注入される（design.md §2-2）。
認可はすべてのメソッドの最初の一文なので、MCP やジョブからの呼び出しもブラウザと
同じチェックを受ける（design.md §5-2、F5）。
"""

import unicodedata
from collections.abc import Iterable, Sequence
from enum import Enum
from typing import Final, Literal

from app.core.authorization import Actor, Permission, ProjectAuthorizer
from app.core.exceptions import (
    InvalidStateTransitionError,
    InvalidTagError,
    NotFoundError,
    VersionConflictError,
)
from app.modules.contents.models import (
    Content,
    ContentRevision,
    ContentStatus,
    RevisionKind,
    Tag,
)
from app.modules.contents.repository import (
    ContentRepository,
    ContentTagRepository,
    ContentTransitionRepository,
    RevisionRepository,
    RevisionSummary,
    TagRepository,
)

# 1コンテンツに付けられるタグの上限（content-pipeline design.md §3-2）。
MAX_TAGS_PER_CONTENT = 10
# NFKC で伸びた後の name_key の上限（列の長さと同じ）。
_TAG_NAME_KEY_MAX_LENGTH = 200


class _Unset(Enum):
    """「省略」と「None（消す）」を区別するための番兵（content-pipeline design.md §6-2）。"""

    UNSET = "UNSET"


UNSET: Final = _Unset.UNSET


def tag_name_key(name: str) -> str:
    """同一判定用のキー：NFKC → casefold → 前後空白除去（content-pipeline design.md §3-2）。

    「Python」と「python」、全角「ＡＷＳ」と「AWS」が同じキーになる。
    """
    return unicodedata.normalize("NFKC", name).casefold().strip()


# 状態遷移表（design.md §8-1 の確定表）。キーが from、値が遷移してよい to の集合。
# published へはこの表から遷移させない。足すと公開物なしで「公開済」にできてしまうため、
# 公開操作の中の mark_published だけが動かす（publishing design.md §4）。
ALLOWED: dict[ContentStatus, frozenset[ContentStatus]] = {
    ContentStatus.INBOX: frozenset({ContentStatus.ADOPTED, ContentStatus.SHELVED}),
    ContentStatus.ADOPTED: frozenset(
        {ContentStatus.INBOX, ContentStatus.DRAFTING, ContentStatus.SHELVED}
    ),
    ContentStatus.DRAFTING: frozenset(
        {ContentStatus.ADOPTED, ContentStatus.IN_REVIEW, ContentStatus.SHELVED}
    ),
    ContentStatus.IN_REVIEW: frozenset({ContentStatus.DRAFTING, ContentStatus.SHELVED}),
    ContentStatus.PUBLISHED: frozenset(),
    ContentStatus.SHELVED: frozenset({ContentStatus.INBOX}),
}

# 公開操作（mark_published）で公開済にしてよい状態（publishing design.md §4）。
# published を含むのは、2つ目のチャネルへの公開・更新で状態を変えないため。
PUBLISHABLE_FROM: frozenset[ContentStatus] = frozenset(
    {ContentStatus.DRAFTING, ContentStatus.IN_REVIEW, ContentStatus.PUBLISHED}
)


class ContentService:
    def __init__(
        self,
        contents: ContentRepository,
        authz: ProjectAuthorizer,
        transitions: ContentTransitionRepository,
        tags: TagRepository,
        content_tags: ContentTagRepository,
        revisions: RevisionRepository,
    ) -> None:
        self._contents = contents
        self._authz = authz
        self._transitions = transitions
        self._tags = tags
        self._content_tags = content_tags
        self._revisions = revisions

    async def create(
        self,
        actor: Actor,
        project_id: int,
        *,
        title: str,
        body_md: str,
        tag_ids: Iterable[int] = (),
        source_note_path: str | None = None,
    ) -> Content:
        """新しいコンテンツは必ず ``inbox`` から始まり、初版のリビジョンを1件持つ（F6・C7）。"""
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        wanted = await self._validated_tag_ids(project_id, tag_ids)
        content = await self._contents.create(
            project_id=project_id,
            title=title,
            body_md=body_md,
            status=ContentStatus.INBOX,
            created_by=actor.user_id,
            source_note_path=source_note_path,
        )
        await self._revisions.append(content, kind=RevisionKind.CREATE, actor_user_id=actor.user_id)
        if wanted:
            await self._content_tags.add(
                project_id=project_id, content_id=content.id, tag_ids=wanted
            )
        await self._contents.reload_tags(content)
        return content

    async def list(
        self,
        actor: Actor,
        project_id: int,
        *,
        statuses: Iterable[ContentStatus] = (),
        tag_ids: Iterable[int] = (),
        q: str | None = None,
    ) -> Sequence[Content]:
        await self._authz.require(actor, project_id, Permission.CONTENT_VIEW)
        return await self._contents.list(project_id, statuses=statuses, tag_ids=tag_ids, q=q)

    async def get(self, actor: Actor, project_id: int, content_id: int) -> Content:
        await self._authz.require(actor, project_id, Permission.CONTENT_VIEW)
        return await self._get_or_404(content_id, project_id)

    async def update(
        self,
        actor: Actor,
        project_id: int,
        content_id: int,
        expected_version: int,
        *,
        title: str | None = None,
        body_md: str | None = None,
        source_note_path: str | None | Literal[_Unset.UNSET] = UNSET,
    ) -> Content:
        """title / body を二段の楽観ロックの下で更新する（design.md §3-3）。

        1段目は、たった今読み込んだ値と ``expected_version`` を比較する。これに
        より、送信前から既に古かったリクエストには何も書き込まず明確な 409 を
        返せる。2段目は flush 時の ``WHERE version = ?``。読み込みと flush の間に
        割り込んだ書き手を捕まえ、repository が同じ 409 にマッピングする。

        変更のない値を送っても UPDATE は発行されず、``version`` はそのまま。
        これは意図した挙動：何も変わっていないなら、他クライアントのコピーが
        古くなったわけでもない。

        title / body_md が実際に変わったときだけ、flush が通った**後**にリビジョンを
        1件残す。楽観ロックに負けた保存（409）は版を残さない（content-pipeline
        design.md §6-2）。``source_note_path`` の変更は ``version`` を進めるが版は作らない。
        """
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        content = await self._get_or_404(content_id, project_id)
        self._check_version(content, expected_version)
        body_changed = (title is not None and title != content.title) or (
            body_md is not None and body_md != content.body_md
        )
        if title is not None:
            content.title = title
        if body_md is not None:
            content.body_md = body_md
        if source_note_path is not UNSET:
            content.source_note_path = source_note_path
        await self._contents.flush()
        if body_changed:
            await self._revisions.append(
                content, kind=RevisionKind.SAVE, actor_user_id=actor.user_id
            )
        return content

    async def set_tags(
        self, actor: Actor, project_id: int, content_id: int, tag_ids: Iterable[int]
    ) -> Content:
        """タグを集合で置き換える（content-pipeline design.md §6-4）。

        ``version`` は進めず、楽観ロックも取らない。集合で送るので、2人が同時に
        付け替えても「半端に混ざる」ことはなく、後勝ちになるだけ。
        """
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        content = await self._get_or_404(content_id, project_id)
        wanted = await self._validated_tag_ids(project_id, tag_ids)
        current = await self._content_tags.tag_ids_of(content.id)
        await self._content_tags.remove(content_id=content.id, tag_ids=current - wanted)
        await self._content_tags.add(
            project_id=project_id, content_id=content.id, tag_ids=wanted - current
        )
        await self._contents.reload_tags(content)
        return content

    async def list_revisions(
        self,
        actor: Actor,
        project_id: int,
        content_id: int,
        *,
        before: int | None = None,
        limit: int = 50,
    ) -> Sequence[RevisionSummary]:
        await self._authz.require(actor, project_id, Permission.CONTENT_VIEW)
        content = await self._get_or_404(content_id, project_id)
        return await self._revisions.list(content.id, before=before, limit=limit)

    async def get_revision(
        self, actor: Actor, project_id: int, content_id: int, revision_no: int
    ) -> ContentRevision:
        await self._authz.require(actor, project_id, Permission.CONTENT_VIEW)
        content = await self._get_or_404(content_id, project_id)
        return await self._get_revision_or_404(content.id, revision_no)

    async def restore(
        self,
        actor: Actor,
        project_id: int,
        content_id: int,
        revision_no: int,
        expected_version: int,
    ) -> Content:
        """指定した版の内容で、新しい版を1件作る。履歴は巻き戻さない（C7・design.md §6-3）。

        今と同じ内容の版を選んだときは何もしない（``version`` もリビジョンも据え置き）。
        """
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        content = await self._get_or_404(content_id, project_id)
        self._check_version(content, expected_version)
        revision = await self._get_revision_or_404(content.id, revision_no)
        if (revision.title, revision.body_md) == (content.title, content.body_md):
            return content
        content.title, content.body_md = revision.title, revision.body_md
        await self._contents.flush()
        await self._revisions.append(
            content,
            kind=RevisionKind.RESTORE,
            actor_user_id=actor.user_id,
            restored_from_no=revision.revision_no,
        )
        return content

    async def delete(self, actor: Actor, project_id: int, content_id: int) -> None:
        """論理削除（design.md §3-2）。後続スペックがこの行を参照し続けるため。"""
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        content = await self._get_or_404(content_id, project_id)
        await self._contents.soft_delete(content)

    async def transition(
        self,
        actor: Actor,
        project_id: int,
        content_id: int,
        to: ContentStatus,
        expected_version: int,
    ) -> Content:
        """status を遷移表（``ALLOWED``）に従って動かし、遷移ログを1行残す（design.md §8-2）。

        version 照合を遷移表チェックより先に行う：古い画面から送られた遷移は、
        遷移の可否より「状態が変わっていた」ことを伝える方がクライアントに役立つため。
        同時に走った二重遷移は、片方が flush 時の ``WHERE version = ?`` で 409 になる。
        """
        await self._authz.require(actor, project_id, Permission.CONTENT_TRANSITION)
        content = await self._get_or_404(content_id, project_id)
        self._check_version(content, expected_version)
        current = ContentStatus(content.status)
        if to not in ALLOWED[current]:
            raise InvalidStateTransitionError(f"cannot transition from {current} to {to}")
        await self._move(content, current, to, actor)
        return content

    # --- publishing から ContentGateway ポート越しに呼ばれる（publishing design.md §2・§4） ---

    async def lock_for_publish(self, actor: Actor, project_id: int, content_id: int) -> Content:
        """公開操作の入口。コンテンツ行を ``FOR UPDATE`` で押さえて返す。

        同じコンテンツへの公開を直列化し、2つ目のリクエストは1つ目の commit を待ってから
        「公開物がもうある」を見る（publishing design.md §10-3）。
        """
        await self._authz.require(actor, project_id, Permission.CONTENT_PUBLISH)
        content = await self._contents.get_for_update(content_id, project_id)
        if content is None:
            raise NotFoundError("content")
        return content

    @staticmethod
    def ensure_publishable(content: Content) -> None:
        """外部に送る前に呼ぶ。送ってから状態で弾くと、記事だけが外に残るため。"""
        if ContentStatus(content.status) not in PUBLISHABLE_FROM:
            raise InvalidStateTransitionError(f"cannot publish from {content.status}")

    async def mark_published(self, actor: Actor, content: Content) -> None:
        """公開物を作ったのと同じトランザクションで公開済にする。

        汎用の遷移表（``ALLOWED``）には published を足さない。足すと公開物なしで
        公開済にできてしまう。すでに公開済なら何もしない（遷移ログも書かない）。
        """
        await self._authz.require(actor, content.project_id, Permission.CONTENT_PUBLISH)
        self.ensure_publishable(content)
        current = ContentStatus(content.status)
        if current is ContentStatus.PUBLISHED:
            return
        await self._move(content, current, ContentStatus.PUBLISHED, actor)

    async def mark_unpublished(self, actor: Actor, content: Content) -> None:
        """取り消されていない公開物が0件になったときに執筆中へ戻す（publishing design.md §4）。"""
        await self._authz.require(actor, content.project_id, Permission.CONTENT_PUBLISH)
        current = ContentStatus(content.status)
        if current is not ContentStatus.PUBLISHED:
            return
        await self._move(content, current, ContentStatus.DRAFTING, actor)

    async def latest_revision_no(self, content: Content) -> int:
        """変換元・原稿の新旧の判定に使う（publishing design.md §3-2）。

        ``content`` は認可を通した取得（``get`` / ``lock_for_publish``）で得たものを渡す。
        """
        return await self._revisions.latest_no(content.id)

    async def _move(
        self, content: Content, current: ContentStatus, to: ContentStatus, actor: Actor
    ) -> None:
        content.status = to.value
        await self._contents.flush()
        await self._transitions.add(
            content_id=content.id, from_status=current, to_status=to, actor_user_id=actor.user_id
        )

    async def _validated_tag_ids(self, project_id: int, tag_ids: Iterable[int]) -> set[int]:
        """全部この企画のタグで、上限以内なら集合にして返す。そうでなければ 422。"""
        wanted = set(tag_ids)
        if len(wanted) > MAX_TAGS_PER_CONTENT:
            raise InvalidTagError(f"at most {MAX_TAGS_PER_CONTENT} tags per content")
        if wanted - await self._tags.existing_ids(project_id, wanted):
            # 他企画のタグと存在しないタグを区別しない（他企画の存在を漏らさない）。
            raise InvalidTagError()
        return wanted

    async def _get_revision_or_404(self, content_id: int, revision_no: int) -> ContentRevision:
        revision = await self._revisions.get(content_id, revision_no)
        if revision is None:
            raise NotFoundError("revision")
        return revision

    async def _get_or_404(self, content_id: int, project_id: int) -> Content:
        # project_id で絞り込んでいるので、他企画のコンテンツ id は単に「無い」。
        content = await self._contents.get(content_id, project_id)
        if content is None:
            raise NotFoundError("content")
        return content

    @staticmethod
    def _check_version(content: Content, expected_version: int) -> None:
        if content.version != expected_version:
            raise VersionConflictError()


class TagService:
    """企画ごとのタグの管理（content-pipeline design.md §6-4）。

    タグの作成・改名・削除は ``CONTENT_WRITE`` に相乗りする。タグはコンテンツに
    付けるためだけに存在するので、別の Permission を作らない（design.md §5）。
    """

    def __init__(self, tags: TagRepository, authz: ProjectAuthorizer) -> None:
        self._tags = tags
        self._authz = authz

    async def list(self, actor: Actor, project_id: int) -> Sequence[tuple[Tag, int]]:
        await self._authz.require(actor, project_id, Permission.CONTENT_VIEW)
        return await self._tags.list_with_usage(project_id)

    async def create(self, actor: Actor, project_id: int, *, name: str) -> Tag:
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        display, key = self._normalize(name)
        return await self._tags.create(project_id=project_id, name=display, name_key=key)

    async def rename(self, actor: Actor, project_id: int, tag_id: int, *, name: str) -> Tag:
        """付与済みのコンテンツへは何もしなくても反映される（中間テーブルは tag_id だけ持つ）。"""
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        tag = await self._get_or_404(tag_id, project_id)
        display, key = self._normalize(name)
        await self._tags.rename(tag, name=display, name_key=key)
        return tag

    async def delete(self, actor: Actor, project_id: int, tag_id: int) -> None:
        """付与も外れる。コンテンツ自体は残る（C1）。"""
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        tag = await self._get_or_404(tag_id, project_id)
        await self._tags.delete(tag)

    async def _get_or_404(self, tag_id: int, project_id: int) -> Tag:
        tag = await self._tags.get(tag_id, project_id)
        if tag is None:
            raise NotFoundError("tag")
        return tag

    @staticmethod
    def _normalize(name: str) -> tuple[str, str]:
        display = name.strip()
        key = tag_name_key(display)
        if not key or len(key) > _TAG_NAME_KEY_MAX_LENGTH:
            raise InvalidTagError("tag name is empty or too long")
        return display, key
