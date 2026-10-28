"""チャネル原稿の編集・保留中の結果の採用・公開画面のまとめのテスト（C4・design.md §9）。"""

import pytest
from app.channels.capabilities import ChannelCode
from app.core.exceptions import ForbiddenError, NotFoundError, VersionConflictError
from app.modules.contents.models import Content, ContentStatus
from app.modules.publishing.models import ChannelDraft
from app.modules.publishing.ports import ConversionOutput

from tests.modules.publishing.conftest import Publishing

QIITA = ChannelCode.QIITA


@pytest.fixture
def p(publishing: Publishing) -> Publishing:
    return publishing


async def _draft(p: Publishing, content: Content) -> ChannelDraft:
    view = await p.drafts.view(p.world.owner, p.world.project, content.id, QIITA)
    assert view.draft is not None
    return view.draft


async def _save(
    p: Publishing, content: Content, version: int, body: str = "直した"
) -> ChannelDraft:
    return await p.drafts.save(
        p.world.owner,
        p.world.project,
        content.id,
        QIITA,
        title="直したタイトル",
        body=body,
        tags=["Python"],
        expected_version=version,
    )


async def test_saving_marks_the_draft_as_hand_edited(p: Publishing) -> None:
    content = await p.content()
    await p.converted(content)
    draft = await _draft(p, content)

    saved = await _save(p, content, draft.version)

    assert (saved.title, saved.body, saved.extra["tags"]) == (
        "直したタイトル",
        "直した",
        ["Python"],
    )
    assert saved.edited_after_apply is True
    assert saved.updated_by == p.world.owner.user_id


async def test_saving_a_stale_version_is_409(p: Publishing) -> None:
    content = await p.content()
    await p.converted(content)
    draft = await _draft(p, content)
    await _save(p, content, draft.version)

    with pytest.raises(VersionConflictError):
        await _save(p, content, draft.version - 1)


async def test_saving_before_any_conversion_is_404(p: Publishing) -> None:
    content = await p.content()

    with pytest.raises(NotFoundError):
        await _save(p, content, 1)


@pytest.mark.parametrize("who", ["reviewer", "demo"])
async def test_reviewer_and_demo_cannot_edit(p: Publishing, who: str) -> None:
    content = await p.content()
    await p.converted(content)
    draft = await _draft(p, content)

    with pytest.raises(ForbiddenError):
        await p.drafts.save(
            getattr(p.world, who),
            p.world.project,
            content.id,
            QIITA,
            title="t",
            body="b",
            tags=[],
            expected_version=draft.version,
        )


async def test_the_pending_result_is_shown_and_can_be_applied(p: Publishing) -> None:
    content = await p.content()
    await p.converted(content)
    draft = await _save(p, content, (await _draft(p, content)).version)

    p.converter.output = ConversionOutput(title="再変換", body="再変換の本文", tags=["AWS"])
    await p.converted(content)
    view = await p.drafts.view(p.world.reviewer, p.world.project, content.id, QIITA)
    assert view.draft is not None and view.draft.body == "直した"
    assert view.pending_job is not None and view.pending_job.result_body == "再変換の本文"

    applied = await p.drafts.apply_pending(
        p.world.editor,
        p.world.project,
        content.id,
        QIITA,
        job_id=view.pending_job.id,
        expected_version=draft.version,
    )

    assert (applied.body, applied.extra) == ("再変換の本文", {"tags": ["AWS"]})
    assert applied.pending_job_id is None
    assert applied.edited_after_apply is False


async def test_applying_a_result_that_is_no_longer_pending_is_409(p: Publishing) -> None:
    content = await p.content()
    await p.converted(content)
    draft = await _save(p, content, (await _draft(p, content)).version)
    await p.converted(content)
    first_pending = draft.pending_job_id
    await p.converted(content)  # もう1回再変換して、保留中が入れ替わった
    assert draft.pending_job_id != first_pending

    with pytest.raises(VersionConflictError):
        await p.drafts.apply_pending(
            p.world.owner,
            p.world.project,
            content.id,
            QIITA,
            job_id=first_pending or 0,
            expected_version=draft.version,
        )


async def test_the_draft_becomes_stale_only_when_the_body_changes(p: Publishing) -> None:
    content = await p.content()
    await p.converted(content)
    view = await p.drafts.view(p.world.owner, p.world.project, content.id, QIITA)
    assert view.draft_is_stale is False

    # 状態遷移（version は進む）では古くならない。
    await p.contents.transition(
        p.world.owner, p.world.project, content.id, ContentStatus.ADOPTED, content.version
    )
    view = await p.drafts.view(p.world.owner, p.world.project, content.id, QIITA)
    assert view.draft_is_stale is False

    await p.contents.update(
        p.world.owner, p.world.project, content.id, content.version, body_md="本文を直した"
    )
    view = await p.drafts.view(p.world.owner, p.world.project, content.id, QIITA)
    assert view.draft_is_stale is True
    assert view.latest_revision_no == 2


async def test_the_view_of_an_unconverted_channel_is_empty(p: Publishing) -> None:
    content = await p.content()

    view = await p.drafts.view(p.world.reviewer, p.world.project, content.id, QIITA)

    assert (view.draft, view.latest_job, view.publication) == (None, None, None)
    assert view.latest_revision_no == 1
