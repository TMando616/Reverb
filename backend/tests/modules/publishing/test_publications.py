"""Qiita への投稿・更新・公開取消のテスト（C6・C8・publishing design.md §10・§11）。

Qiita API は呼ばない（``FakeQiita``）。
"""

from datetime import UTC, datetime

import pytest
from app.channels.capabilities import ChannelCode
from app.core.exceptions import (
    ForbiddenError,
    InvalidDraftError,
    InvalidStateTransitionError,
    NotFoundError,
    PublicationExistsError,
    QiitaItemMissingError,
    QiitaRateLimitedAppError,
    QiitaRejectedPublishError,
    QiitaTokenInvalidError,
    QiitaTokenMissingError,
    QiitaUnavailableAppError,
    VersionConflictError,
)
from app.modules.contents.models import Content, ContentStatus
from app.modules.publishing.models import ChannelDraft, Publication, Visibility
from app.modules.publishing.ports import (
    QiitaAuthError,
    QiitaError,
    QiitaNotFoundError,
    QiitaRateLimitedError,
    QiitaRejectedError,
    QiitaUnavailableError,
)
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from tests.modules.publishing.conftest import Publishing

TOKEN = "owner-qiita-token"
S = ContentStatus


@pytest.fixture
async def p(publishing: Publishing) -> Publishing:
    await publishing.accounts.register_qiita(publishing.world.owner, TOKEN)
    publishing.qiita.tokens_seen.clear()
    return publishing


async def _ready(p: Publishing, status: ContentStatus = S.DRAFTING) -> tuple[Content, ChannelDraft]:
    """変換済みで、指定の状態にあるコンテンツと原稿。"""
    content = await p.content()
    await p.converted(content)
    content.status = status.value
    await p.session.flush()
    view = await p.drafts.view(p.world.owner, p.world.project, content.id, ChannelCode.QIITA)
    assert view.draft is not None
    return content, view.draft


async def _publish(
    p: Publishing,
    content: Content,
    draft: ChannelDraft,
    visibility: Visibility = Visibility.PRIVATE,
) -> Publication:
    return await p.publications.publish_qiita(
        p.world.owner,
        p.world.project,
        content.id,
        visibility=visibility,
        expected_draft_version=draft.version,
    )


async def _set_tags(p: Publishing, draft: ChannelDraft, tags: list[str]) -> None:
    draft.extra = {"tags": tags}
    await p.session.flush()


# --- 新規投稿 ---


@pytest.mark.parametrize("start", [S.DRAFTING, S.IN_REVIEW])
async def test_publishing_records_the_publication_and_marks_published(
    p: Publishing, start: ContentStatus
) -> None:
    content, draft = await _ready(p, start)

    publication = await _publish(p, content, draft)

    token, item = p.qiita.created[0]
    assert token == TOKEN
    assert (item.title, item.tags, item.private) == (draft.title, ["Python", "FastAPI"], True)
    assert (publication.external_id, publication.visibility) == ("item0001", "private")
    assert publication.url == "https://qiita.com/t_mando_/items/item0001"
    assert publication.published_by == p.world.owner.user_id
    assert content.status == S.PUBLISHED


async def test_publishing_twice_is_409_and_does_not_post_again(p: Publishing) -> None:
    content, draft = await _ready(p)
    await _publish(p, content, draft)

    with pytest.raises(PublicationExistsError):
        await _publish(p, content, draft)

    assert len(p.qiita.created) == 1


@pytest.mark.parametrize("who", ["editor", "reviewer", "demo"])
async def test_only_the_owner_can_publish(p: Publishing, who: str) -> None:
    content, draft = await _ready(p)

    with pytest.raises(ForbiddenError):
        await p.publications.publish_qiita(
            getattr(p.world, who),
            p.world.project,
            content.id,
            visibility=Visibility.PRIVATE,
            expected_draft_version=draft.version,
        )
    assert p.qiita.created == []


@pytest.mark.parametrize("start", [S.INBOX, S.ADOPTED, S.SHELVED])
async def test_cannot_publish_before_writing_and_nothing_is_sent(
    p: Publishing, start: ContentStatus
) -> None:
    content, draft = await _ready(p, start)

    with pytest.raises(InvalidStateTransitionError):
        await _publish(p, content, draft)
    assert p.qiita.created == []


async def test_a_stale_draft_version_is_409(p: Publishing) -> None:
    content, draft = await _ready(p)

    with pytest.raises(VersionConflictError):
        await p.publications.publish_qiita(
            p.world.owner,
            p.world.project,
            content.id,
            visibility=Visibility.PRIVATE,
            expected_draft_version=draft.version + 1,
        )


@pytest.mark.parametrize("tags", [[], ["a", "b", "c", "d", "e", "f"], ["  "]])
async def test_qiita_tag_rules_are_checked_before_sending(p: Publishing, tags: list[str]) -> None:
    content, draft = await _ready(p)
    await _set_tags(p, draft, tags)

    with pytest.raises(InvalidDraftError):
        await _publish(p, content, draft)
    assert p.qiita.created == []


async def test_duplicate_tags_are_sent_once(p: Publishing) -> None:
    content, draft = await _ready(p)
    await _set_tags(p, draft, ["Python", "Python ", "FastAPI"])

    await _publish(p, content, draft)

    assert p.qiita.created[0][1].tags == ["Python", "FastAPI"]


async def test_without_a_token_it_is_409(p: Publishing, db_session: AsyncSession) -> None:
    content, draft = await _ready(p)
    await p.accounts.delete_qiita(p.world.owner)

    with pytest.raises(QiitaTokenMissingError):
        await _publish(p, content, draft)


async def test_another_owners_token_is_not_used(p: Publishing) -> None:
    # 企画の owner が複数いても、公開した本人のトークンで投稿する（design.md §5）。
    content, draft = await _ready(p)

    await _publish(p, content, draft)

    assert p.qiita.tokens_seen == [TOKEN]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (QiitaAuthError("Unauthorized"), QiitaTokenInvalidError),
        (QiitaRejectedError("Bad tags"), QiitaRejectedPublishError),
        (QiitaRateLimitedError("slow down"), QiitaRateLimitedAppError),
        (QiitaUnavailableError("down"), QiitaUnavailableAppError),
    ],
)
async def test_qiita_errors_map_to_app_errors_and_nothing_is_recorded(
    p: Publishing, error: QiitaError, expected: type[Exception]
) -> None:
    content, draft = await _ready(p)
    p.qiita.fail_with = error

    with pytest.raises(expected):
        await _publish(p, content, draft)

    assert content.status == S.DRAFTING
    view = await p.drafts.view(p.world.owner, p.world.project, content.id, ChannelCode.QIITA)
    assert view.publication is None


# --- 更新 ---


async def test_push_updates_the_item_without_changing_the_state(p: Publishing) -> None:
    content, draft = await _ready(p)
    publication = await _publish(p, content, draft)
    draft.body = "直した本文"
    await p.session.flush()

    pushed = await p.publications.push_qiita(
        p.world.owner,
        p.world.project,
        content.id,
        expected_draft_version=draft.version,
        visibility=Visibility.PUBLIC,
    )

    token, item_id, item = p.qiita.updated[0]
    assert (token, item_id, item.body, item.private) == (TOKEN, "item0001", "直した本文", False)
    assert pushed.id == publication.id
    assert pushed.visibility == "public"
    assert pushed.last_pushed_at is not None
    assert content.status == S.PUBLISHED


async def test_push_keeps_the_visibility_when_omitted(p: Publishing) -> None:
    content, draft = await _ready(p)
    await _publish(p, content, draft)

    pushed = await p.publications.push_qiita(
        p.world.owner, p.world.project, content.id, expected_draft_version=draft.version
    )

    assert pushed.visibility == "private"
    assert p.qiita.updated[0][2].private is True


async def test_a_public_item_cannot_go_back_to_private(p: Publishing) -> None:
    content, draft = await _ready(p)
    await _publish(p, content, draft, Visibility.PUBLIC)

    with pytest.raises(InvalidDraftError):
        await p.publications.push_qiita(
            p.world.owner,
            p.world.project,
            content.id,
            expected_draft_version=draft.version,
            visibility=Visibility.PRIVATE,
        )
    assert p.qiita.updated == []


async def test_push_without_a_publication_is_404(p: Publishing) -> None:
    content, draft = await _ready(p)

    with pytest.raises(NotFoundError):
        await p.publications.push_qiita(
            p.world.owner, p.world.project, content.id, expected_draft_version=draft.version
        )


async def test_push_to_an_item_deleted_on_qiita_is_409(p: Publishing) -> None:
    content, draft = await _ready(p)
    await _publish(p, content, draft)
    p.qiita.fail_with = QiitaNotFoundError("Not found")

    with pytest.raises(QiitaItemMissingError):
        await p.publications.push_qiita(
            p.world.owner, p.world.project, content.id, expected_draft_version=draft.version
        )


# --- 取消と一覧 ---


async def test_cancel_returns_to_drafting_and_does_not_touch_qiita(p: Publishing) -> None:
    content, draft = await _ready(p)
    publication = await _publish(p, content, draft)

    await p.publications.cancel(p.world.owner, p.world.project, publication.id)

    assert publication.cancelled_at is not None
    assert publication.cancelled_by == p.world.owner.user_id
    assert content.status == S.DRAFTING
    assert p.qiita.updated == []
    # 取り消したあとは、もう一度投稿できる。
    await _publish(p, content, draft)
    assert len(p.qiita.created) == 2


async def test_cancel_keeps_published_while_another_channel_remains(p: Publishing) -> None:
    content, draft = await _ready(p)
    qiita = await _publish(p, content, draft)
    # 2つ目のチャネル（M3 の貼り戻し相当）を直接作る。
    p.session.add(
        Publication(
            project_id=content.project_id,
            content_id=content.id,
            channel="note",
            external_id="n123",
            url="https://note.com/u/n/n123",
            published_by=p.world.owner.user_id,
        )
    )
    await p.session.flush()

    await p.publications.cancel(p.world.owner, p.world.project, qiita.id)

    assert content.status == S.PUBLISHED


async def test_cancelling_twice_is_404(p: Publishing) -> None:
    content, draft = await _ready(p)
    publication = await _publish(p, content, draft)
    await p.publications.cancel(p.world.owner, p.world.project, publication.id)

    with pytest.raises(NotFoundError):
        await p.publications.cancel(p.world.owner, p.world.project, publication.id)


@pytest.mark.parametrize("who", ["editor", "reviewer", "demo"])
async def test_only_the_owner_can_cancel(p: Publishing, who: str) -> None:
    content, draft = await _ready(p)
    publication = await _publish(p, content, draft)

    with pytest.raises(ForbiddenError):
        await p.publications.cancel(getattr(p.world, who), p.world.project, publication.id)


async def test_cancelling_from_another_project_is_404(p: Publishing) -> None:
    content, draft = await _ready(p)
    publication = await _publish(p, content, draft)

    with pytest.raises(NotFoundError):
        await p.publications.cancel(p.world.owner, p.world.other_project, publication.id)


async def test_the_project_list_groups_by_content_and_hides_cancelled(p: Publishing) -> None:
    first, first_draft = await _ready(p)
    await _publish(p, first, first_draft)
    second, second_draft = await _ready(p)
    cancelled = await _publish(p, second, second_draft)
    await p.publications.cancel(p.world.owner, p.world.project, cancelled.id)
    third, third_draft = await _ready(p)
    latest = await _publish(p, third, third_draft)
    latest.published_at = datetime(2099, 1, 1, tzinfo=UTC)
    await p.session.flush()

    entries = await p.publications.list_for_project(p.world.reviewer, p.world.project)

    assert [e.content_id for e in entries] == [third.id, first.id]
    assert [pub.channel for pub in entries[0].publications] == ["qiita"]


async def test_a_cancel_that_lost_the_race_is_404_and_keeps_the_first_record(
    p: Publishing,
) -> None:
    content, draft = await _ready(p)
    publication = await _publish(p, content, draft)
    # 別のリクエストが先に取り消した（この画面が持っているオブジェクトは古いまま）。
    first = datetime(2026, 1, 1, tzinfo=UTC)
    await p.session.execute(
        update(Publication)
        .where(Publication.id == publication.id)
        .values(cancelled_at=first, cancelled_by=p.world.owner.user_id)
        .execution_options(synchronize_session=False)
    )
    assert publication.cancelled_at is None

    with pytest.raises(NotFoundError):
        await p.publications.cancel(p.world.owner, p.world.project, publication.id)

    assert publication.cancelled_at == first


async def test_the_list_can_be_narrowed_to_one_content(p: Publishing) -> None:
    first, first_draft = await _ready(p)
    await _publish(p, first, first_draft)
    second, second_draft = await _ready(p)
    await _publish(p, second, second_draft)

    entries = await p.publications.list_for_project(
        p.world.reviewer, p.world.project, content_id=second.id
    )

    assert [e.content_id for e in entries] == [second.id]
