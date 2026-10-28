"""変換プロンプトの組み立て（publishing design.md §8-2）。

system は「固定部分（チャネルごとに同じ）＋プロファイル部分」、user は変換する本文。
本文は切り詰めない（上限は content-pipeline の 10万文字で、文脈長に十分収まる）。
"""

from typing import Any

from app.modules.publishing.ports import ConversionInput

# structured outputs の形（design.md §8-1）。Qiita 以外のチャネルでも同じ形で受け、
# タグを使わないチャネルは空配列を返させる。
OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "チャネル向けのタイトル"},
        "body": {"type": "string", "description": "チャネル向けの本文"},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "チャネルのタグ候補（Qiita なら技術名を1〜5個）",
        },
    },
    "required": ["title", "body", "tags"],
    "additionalProperties": False,
}


def build_system(request: ConversionInput) -> str:
    fmt = (
        "Markdown"
        if request.format == "markdown"
        else "プレーンテキスト（Markdown 記法を使わない）"
    )
    length = f"本文は {request.max_length} 文字以内にしてください。\n" if request.max_length else ""
    profile = request.profile
    banned = "\n".join(f"- {phrase}" for phrase in profile.banned_phrases) or "- （なし）"
    return f"""\
あなたは、発信者本人の文体を保ったまま、元の原稿を{request.channel_label}向けの原稿に書き直す編集者です。

## 出力
- title：{request.channel_label}向けのタイトル
- body：{request.channel_label}向けの本文。形式は{fmt}
- tags：{request.channel_label}のタグ候補。
  既存タグの一覧に合うものがあれば、その表記を優先してください
{length}
## 守ること
- 元の本文に無い事実・体験・数値を足さないでください。
  構成を整えるために補った文は最小限にしてください
- 本人の一人称・口癖・言い回しを変えないでください。言葉は元の本文から引いてください
- 元の本文に書かれた手順やコードは、意味を変えずに残してください

## 書き分けルール：構成
{profile.structure}

## 書き分けルール：語尾・文体
{profile.tone}

## 書き分けルール：一人称
{profile.first_person}

## 書き分けルール：使わない表現
{banned}
"""


def build_user(request: ConversionInput) -> str:
    tags = "、".join(request.existing_tags) if request.existing_tags else "（なし）"
    return f"""\
次の原稿を書き直してください。

<title>
{request.title}
</title>

<body>
{request.body_md}
</body>

<existing_tags>
{tags}
</existing_tags>
"""
