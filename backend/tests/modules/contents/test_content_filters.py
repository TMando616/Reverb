"""一覧の絞り込みと ``source_note_path`` のテスト（content-pipeline C3・C4・tasks.md 3.4）。"""

import pytest
from app.modules.contents.models import ContentStatus
from app.modules.contents.schemas import ContentCreateRequest, ContentUpdateRequest
from pydantic import ValidationError

from tests.modules.contents.conftest import World


async def _titles(world: World, **filters: object) -> list[str]:
    rows = await world.contents.list(world.owner, world.project, **filters)  # type: ignore[arg-type]
    return sorted(c.title for c in rows)


async def test_tags_are_and_ed(world: World) -> None:
    aws = await world.tags.create(world.owner, world.project, name="AWS")
    ci = await world.tags.create(world.owner, world.project, name="CI")
    await world.contents.create(
        world.owner, world.project, title="両方", body_md="", tag_ids=[aws.id, ci.id]
    )
    await world.contents.create(
        world.owner, world.project, title="AWSだけ", body_md="", tag_ids=[aws.id]
    )
    await world.contents.create(world.owner, world.project, title="なし", body_md="")

    assert await _titles(world, tag_ids=[aws.id]) == ["AWSだけ", "両方"]
    assert await _titles(world, tag_ids=[aws.id, ci.id]) == ["両方"]
    # 同じ ID を重ねても「2つ持つ」扱いにならない
    assert await _titles(world, tag_ids=[aws.id, aws.id]) == ["AWSだけ", "両方"]


async def test_statuses_are_or_ed(world: World) -> None:
    inbox = await world.contents.create(world.owner, world.project, title="受信箱", body_md="")
    adopted = await world.contents.create(world.owner, world.project, title="採用", body_md="")
    await world.contents.transition(
        world.owner, world.project, adopted.id, ContentStatus.ADOPTED, 1
    )
    shelved = await world.contents.create(world.owner, world.project, title="見送り", body_md="")
    await world.contents.transition(
        world.owner, world.project, shelved.id, ContentStatus.SHELVED, 1
    )

    assert await _titles(world, statuses=[ContentStatus.INBOX, ContentStatus.ADOPTED]) == [
        "受信箱",
        "採用",
    ]
    assert inbox.status == ContentStatus.INBOX


async def test_keyword_matches_title_or_body_case_insensitively(world: World) -> None:
    await world.contents.create(world.owner, world.project, title="Docker入門", body_md="")
    await world.contents.create(world.owner, world.project, title="メモ", body_md="docker compose")
    await world.contents.create(world.owner, world.project, title="無関係", body_md="")

    assert await _titles(world, q="DOCKER") == ["Docker入門", "メモ"]


async def test_like_wildcards_in_keyword_are_literal(world: World) -> None:
    await world.contents.create(world.owner, world.project, title="100%の話", body_md="")
    await world.contents.create(world.owner, world.project, title="1000の話", body_md="")
    await world.contents.create(world.owner, world.project, title="snake_case", body_md="")
    await world.contents.create(world.owner, world.project, title="snakeXcase", body_md="")
    await world.contents.create(world.owner, world.project, title="C:\\path", body_md="")

    assert await _titles(world, q="100%") == ["100%の話"]
    assert await _titles(world, q="e_c") == ["snake_case"]
    assert await _titles(world, q="\\p") == ["C:\\path"]


async def test_filters_combine_and_stay_in_the_project(world: World) -> None:
    aws = await world.tags.create(world.owner, world.project, name="AWS")
    other_aws = await world.tags.create(world.owner, world.other_project, name="AWS")
    await world.contents.create(
        world.owner, world.project, title="Docker on AWS", body_md="", tag_ids=[aws.id]
    )
    await world.contents.create(world.owner, world.project, title="Docker", body_md="")
    await world.contents.create(
        world.owner,
        world.other_project,
        title="Docker on AWS（他企画）",
        body_md="",
        tag_ids=[other_aws.id],
    )

    assert await _titles(world, statuses=[ContentStatus.INBOX], tag_ids=[aws.id], q="docker") == [
        "Docker on AWS"
    ]
    # 他企画のタグ ID を渡しても、他企画のコンテンツは出てこない
    assert await _titles(world, tag_ids=[other_aws.id]) == []


async def test_list_is_ordered_by_last_update(world: World) -> None:
    first = await world.contents.create(world.owner, world.project, title="先", body_md="")
    await world.contents.create(world.owner, world.project, title="後", body_md="")

    rows = await world.contents.list(world.owner, world.project)
    # 同じトランザクション内では now() が同じなので、同時刻は id の新しい順になる
    assert [c.title for c in rows] == ["後", "先"]
    assert first.id < rows[0].id


async def test_source_note_path_is_kept_and_cleared(world: World) -> None:
    content = await world.contents.create(
        world.owner, world.project, title="a", body_md="", source_note_path="01_メモ/ネタ.md"
    )
    assert content.source_note_path == "01_メモ/ネタ.md"

    updated = await world.contents.update(
        world.editor, world.project, content.id, content.version, source_note_path=None
    )
    assert updated.source_note_path is None
    # パスの変更は version を進める（design.md §4）
    assert updated.version == 2


@pytest.mark.parametrize(
    "path",
    [
        "/Users/me/vault/a.md",
        "\\\\server\\share\\a.md",
        "C:\\vault\\a.md",
        "c:a.md",
        "../secret.md",
        "notes/../../etc/passwd",
        "notes\\..\\x.md",
        "a\x00.md",
        "a\n.md",
        "",
        "a" * 501,
    ],
)
def test_invalid_source_note_paths_are_rejected(path: str) -> None:
    with pytest.raises(ValidationError):
        ContentCreateRequest(title="a", source_note_path=path)


def test_backslashes_are_normalized_to_slashes() -> None:
    body = ContentCreateRequest(title="a", source_note_path="02_アウトプット\\記事.md")

    assert body.source_note_path == "02_アウトプット/記事.md"


def test_update_distinguishes_omitted_from_null() -> None:
    omitted = ContentUpdateRequest(expected_version=1, title="a")
    cleared = ContentUpdateRequest(expected_version=1, source_note_path=None)

    assert "source_note_path" not in omitted.model_fields_set
    assert "source_note_path" in cleared.model_fields_set
