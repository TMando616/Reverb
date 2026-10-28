"""変換プロンプトの組み立てのテスト（publishing design.md §8-2）。"""

from app.channels.capabilities import ChannelCode
from app.llm.prompts import build_system, build_user
from app.modules.publishing.ports import ConversionInput
from app.modules.publishing.profiles import DEFAULT_PROFILES


def _input(body: str = "本文", tags: list[str] | None = None) -> ConversionInput:
    return ConversionInput(
        channel_label="Qiita",
        format="markdown",
        max_length=None,
        title="ECS の話",
        body_md=body,
        profile=DEFAULT_PROFILES[ChannelCode.QIITA],
        existing_tags=tags or [],
    )


def test_system_prompt_lists_every_rule_of_the_profile() -> None:
    system = build_system(_input())
    profile = DEFAULT_PROFILES[ChannelCode.QIITA]

    assert profile.structure in system
    assert profile.tone in system
    assert profile.first_person in system
    for phrase in profile.banned_phrases:
        assert f"- {phrase}" in system


def test_user_prompt_keeps_the_whole_body_and_existing_tags() -> None:
    body = "あ" * 100_000

    user = build_user(_input(body=body, tags=["AWS", "ECS"]))

    assert body in user
    assert "AWS、ECS" in user
    assert "ECS の話" in user


def test_the_system_prompt_does_not_depend_on_the_body() -> None:
    # 本文はユーザー側にだけ入れる（system にユーザーデータを混ぜない）。
    assert build_system(_input(body="秘密の本文")) == build_system(_input(body="別の本文"))
