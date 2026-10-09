"""OpenAPI スキーマを JSON ファイルに書き出す（content-pipeline design.md §9-9）。

フロントの型は手書きせず、この出力から ``openapi-typescript`` で生成する（frontend.md §4）。
HTTP サーバーも DB も起動せずにスキーマだけ作れるよう、アプリを組み立てて
``app.openapi()`` を呼ぶだけにしている。

    uv run python -m app.export_openapi ../frontend/openapi.json
"""

import json
import sys
from pathlib import Path

from app.main import app


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.export_openapi <output-path>")
    # キー順を固定して、API が変わっていないのに差分が出ることを防ぐ。
    text = json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    Path(sys.argv[1]).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
