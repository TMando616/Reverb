"""変換の受付・ワーカー・原稿への反映のテスト（C2・C3・C4・publishing design.md §7・§9-2）。

Claude API は呼ばない（``FakeConverter``）。ワーカーはループではなく ``run_once`` を直接呼ぶ。
"""

from datetime import UTC, datetime, timedelta

import pytest
from app.channels.capabilities import ChannelCode
from app.core.exceptions import (
    ConversionInProgressError,
    ForbiddenError,
    NotFoundError,
    UnsupportedChannelError,
)
from app.jobs.worker import run_once
from app.modules.contents.models import Content
from app.modules.publishing.models import ChannelDraft, ConversionJob, JobStatus
from app.modules.publishing.ports import ConversionOutput
from sqlalchemy import select, update

from tests.modules.publishing.conftest import Publishing
from tests.modules.publishing.fakes import conversion_failed

QIITA = ChannelCode.QIITA


@pytest.fixture
def p(publishing: Publishing) -> Publishing:
    return publishing


async def _request(p: Publishing, content: Content) -> ConversionJob:
    return await p.conversions.request(p.world.owner, p.world.project, content.id, QIITA)


async def _work(p: Publishing) -> bool:
    return await run_once(p.sessions(), p.converter, build=lambda _s: p.conversions)


async def _draft(p: Publishing, content: Content) -> ChannelDraft | None:
    result = await p.session.scalars(
        select(ChannelDraft).where(ChannelDraft.content_id == content.id)
    )
    return result.one_or_none()


# --- 受付 ---


async def test_request_queues_a_job_with_the_profile_and_latest_revision(p: Publishing) -> None:
    content = await p.content()
    await p.contents.update(p.world.owner, p.world.project, content.id, 1, body_md="第2稿")

    job = await _request(p, content)

    assert job.status == JobStatus.QUEUED
    assert job.source_revision_no == 2
    assert job.model == "claude-opus-5-5"
    assert job.profile_snapshot["first_person"] == "僕"
    assert job.profile_snapshot["version"] == 1
    assert "いかがでしたか？" in job.profile_snapshot["banned_phrases"]


async def test_editor_can_convert(p: Publishing) -> None:
    content = await p.content()

    job = await p.conversions.request(p.world.editor, p.world.project, content.id, QIITA)

    assert job.requested_by == p.world.editor.user_id


@pytest.mark.parametrize("who", ["reviewer", "demo"])
async def test_reviewer_and_demo_cannot_convert(p: Publishing, who: str) -> None:
    content = await p.content()

    with pytest.raises(ForbiddenError):
        await p.conversions.request(getattr(p.world, who), p.world.project, content.id, QIITA)


async def test_another_projects_content_is_not_found(p: Publishing) -> None:
    content = await p.content()

    with pytest.raises(NotFoundError):
        await p.conversions.request(p.world.owner, p.world.other_project, content.id, QIITA)


async def test_a_second_request_while_one_is_pending_is_409(p: Publishing) -> None:
    content = await p.content()
    await _request(p, content)

    with pytest.raises(ConversionInProgressError):
        await _request(p, content)


async def test_channels_without_a_profile_are_not_supported_yet(p: Publishing) -> None:
    content = await p.content()

    with pytest.raises(UnsupportedChannelError):
        await p.conversions.request(p.world.owner, p.world.project, content.id, ChannelCode.X)


# --- ワーカー ---


async def test_worker_converts_the_requested_revision_and_creates_the_draft(
    p: Publishing,
) -> None:
    content = await p.content(body="第1稿")
    job = await _request(p, content)
    # 依頼のあとに本文が変わっても、変換するのは依頼したときの版。
    await p.contents.update(p.world.owner, p.world.project, content.id, 1, body_md="第2稿")

    assert await _work(p) is True

    sent = p.converter.inputs[0]
    assert (sent.title, sent.body_md, sent.channel_label) == ("ECS の話", "第1稿", "Qiita")
    assert job.status == JobStatus.SUCCEEDED
    assert (job.result_title, job.input_tokens, job.request_id) == (
        "Qiita 向けタイトル",
        100,
        "req_fake",
    )
    draft = await _draft(p, content)
    assert draft is not None
    assert (draft.title, draft.extra, draft.source_revision_no) == (
        "Qiita 向けタイトル",
        {"tags": ["Python", "FastAPI"]},
        1,
    )
    assert draft.applied_job_id == job.id
    assert draft.edited_after_apply is False


async def test_worker_with_nothing_queued_does_nothing(p: Publishing) -> None:
    assert await _work(p) is False
    assert p.converter.inputs == []


@pytest.mark.parametrize(
    "code", ["rate_limited", "upstream_unavailable", "misconfigured", "refused", "truncated"]
)
async def test_conversion_failures_are_recorded_with_their_code(p: Publishing, code: str) -> None:
    content = await p.content()
    job = await _request(p, content)
    p.converter.fail_with = conversion_failed(code)

    await _work(p)

    assert (job.status, job.error_code, job.request_id) == (JobStatus.FAILED, code, "req_fail")
    assert await _draft(p, content) is None
    # 終わった行は部分 UNIQUE から外れるので、すぐ再実行できる。
    await _request(p, content)


async def test_an_unexpected_crash_does_not_leave_the_job_running(p: Publishing) -> None:
    content = await p.content()
    job = await _request(p, content)
    p.converter.fail_with = RuntimeError("bug")

    await _work(p)

    assert (job.status, job.error_code) == (JobStatus.FAILED, "internal_error")


async def test_a_requester_who_lost_access_fails_the_job(p: Publishing) -> None:
    content = await p.content()
    job = await p.conversions.request(p.world.editor, p.world.project, content.id, QIITA)
    await p.contents.delete(p.world.owner, p.world.project, content.id)

    assert await _work(p) is False

    assert (job.status, job.error_code) == (JobStatus.FAILED, "source_unavailable")
    assert p.converter.inputs == []


async def test_stuck_jobs_are_reaped_and_late_results_dropped(p: Publishing) -> None:
    content = await p.content()
    job = await _request(p, content)
    claimed = await p.conversions.claim()
    assert claimed is not None
    await p.session.execute(
        update(ConversionJob)
        .where(ConversionJob.id == job.id)
        .values(started_at=datetime.now(UTC) - timedelta(minutes=16))
    )

    assert await p.conversions.reap_stuck() == 1
    await p.session.refresh(job)
    assert (job.status, job.error_code) == (JobStatus.FAILED, "interrupted")

    await p.conversions.complete(job.id, p.converter.output)
    await p.session.refresh(job)
    assert job.status == JobStatus.FAILED
    assert await _draft(p, content) is None


async def test_a_recent_running_job_is_not_reaped(p: Publishing) -> None:
    content = await p.content()
    await _request(p, content)
    await p.conversions.claim()

    assert await p.conversions.reap_stuck() == 0


# --- 原稿への反映（§9-2） ---


async def test_reconversion_replaces_an_untouched_draft(p: Publishing) -> None:
    content = await p.content()
    await _request(p, content)
    await _work(p)
    draft = await _draft(p, content)
    assert draft is not None
    version = draft.version

    p.converter.output = ConversionOutput(title="2回目", body="新しい本文", tags=["AWS"])
    second = await _request(p, content)
    await _work(p)

    assert (draft.title, draft.body, draft.extra) == ("2回目", "新しい本文", {"tags": ["AWS"]})
    assert draft.applied_job_id == second.id
    assert draft.version == version + 1
    assert draft.pending_job_id is None


async def test_reconversion_keeps_a_hand_edited_draft_and_holds_the_result(p: Publishing) -> None:
    content = await p.content()
    await _request(p, content)
    await _work(p)
    draft = await _draft(p, content)
    assert draft is not None
    draft.body = "手で直した本文"
    draft.edited_after_apply = True
    await p.session.flush()

    second = await _request(p, content)
    await _work(p)

    assert draft.body == "手で直した本文"
    assert draft.pending_job_id == second.id


# --- 照会 ---


async def test_history_is_newest_first_and_visible_to_reviewers(p: Publishing) -> None:
    content = await p.content()
    first = await _request(p, content)
    await _work(p)
    second = await _request(p, content)

    jobs = await p.conversions.list_jobs(p.world.reviewer, p.world.project, content.id)

    assert [j.id for j in jobs] == [second.id, first.id]
    got = await p.conversions.get_job(p.world.reviewer, p.world.project, content.id, first.id)
    assert got.status == JobStatus.SUCCEEDED


async def test_a_job_of_another_content_is_not_found(p: Publishing) -> None:
    content = await p.content()
    other = await p.content(title="別のネタ")
    job = await _request(p, content)

    with pytest.raises(NotFoundError):
        await p.conversions.get_job(p.world.owner, p.world.project, other.id, job.id)
