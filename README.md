# Reverb

**「書いたあとに何が起きたか」を記録し続けるための箱。**

Obsidian の断片ノートから、記事ネタ・執筆・レビュー・公開を経て、**反応の日次追跡**までを1本のパイプラインにする発信オペレーション基盤。Qiita・note・X・ポッドキャストを同じ器で横断的に扱う。

> 🚧 **開発中**（2026年9月〜12月）。進捗は [`.kiro/specs/`](.kiro/specs/) を参照。

---

## なぜ作ったか

Qiita も note も Spotify も、**「現在値」しか見せてくれない。**

Qiita が教えてくれるのは今の LGTM 数だけで、「公開後3日で伸びたのか、じわじわ伸びたのか」は分からない。日次でスナップショットを取り続けない限り、この区別は永久につかない。

note の収益化を目指して文献を100本読んだが、**学んだことを自分の記事に適用した結果を測る手段がなかった。** それが作った理由。

---

## 主な機能

| | |
|---|---|
| **ネタの在庫管理** | `受信箱 → 採用 → 執筆中 → レビュー中 → 公開済 → 見送り` の状態遷移で管理 |
| **執筆とレビュー** | Markdown エディタ、リビジョン履歴、行アンカー付きコメント、セクション単位の編集ロック |
| **チャネル変換** | 1つの本文から Qiita 体裁 / note 体裁 / X 告知文（280字）を生成 |
| **公開** | Qiita は API で自動、X は Web Intent、note は手動補助 |
| **指標の日次収集** | 全チャネルの数値を毎日自動取得し、推移を保存 |
| **分析** | 公開後 N 日の伸びカーブ、タグ別・曜日別・文字数帯別の比較 |
| **MCP サーバー** | 手元の Claude Code から、Obsidian を読ませてネタを流し込める |

---

## 技術スタック

| 領域 | 採用 |
|---|---|
| バックエンド | Python / FastAPI |
| フロントエンド | Next.js 16 / React 19 |
| DB | PostgreSQL |
| キュー | Redis ベースのジョブ基盤（未決・ADR-0013） |
| リアルタイム | WebSocket（編集ロック・コメント）／ SSE（ジョブ進捗） |
| LLM | Claude API |
| インフラ | AWS / GitHub Actions |

---

## アーキテクチャ

```
ローカル（WSL）                        AWS
┌──────────────────┐              ┌────────────────────────┐
│  Claude Code     │              │  Next.js（フロント）     │
│   ↕ Obsidian     │              │        ↕                │
│  （断片メモを読む）│◄────MCP─────►│  FastAPI               │
└──────────────────┘   (トークン   │   + MCPサーバー         │
                        認証)      │   + チャネルアダプタ     │
                                   │        ↕                │
                                   │  PostgreSQL / Redis     │
                                   └────────────────────────┘
                                            ↕
                                   Qiita API / note / RSS
```

**Obsidian Vault はローカルにあり、AWS 上のサービスからは物理的に到達できない。**
そこで Vault を読むのはローカルの Claude Code の役割とし、結果だけを MCP 経由でサービスに書き込む構成にしている。

---

## 設計上の判断

主要な判断は [`docs/adr/`](docs/adr/) に記録している。抜粋：

| 判断 | 要旨 |
|---|---|
| **共同編集に CRDT（Yjs）を使わない** | ライブラリが排他制御を全部引き受けると、設計が成果物として残らない。セクション単位の編集ロックと楽観ロックを自前で設計した |
| **外部公開を3モードで抽象化** | 5プラットフォームを調べた結果、公開 API があるのは Qiita のみ。`auto` / `intent` / `manual` の3モードで UI とジョブの分岐を1箇所に集約した |
| **iframe 埋め込みは採用しない** | 各社が `X-Frame-Options: DENY` を返し、仮に埋め込めても同一オリジンポリシーで DOM を操作できない。代わりに X の Web Intent を採用し、OAuth 実装なしで1クリック公開を実現した |
| **ブラウザ内ターミナルを採用しない** | 出力が文字列で構造化データにならず DB に残せない。加えて公開デプロイに RCE 面を作ることになる。MCP サーバー方式に切り替えた |

---

## 開発の進め方

**CC-SDD（仕様駆動開発）** で進めている。ステアリング → 要件 → 設計 → タスク → 実装の順で、各フェーズに人間のレビューを挟む。

```
.kiro/
├── steering/          プロジェクト全体のルール
│   ├── product.md
│   ├── tech.md
│   └── structure.md
└── specs/{feature}/   機能ごとの仕様
    ├── requirements.md
    ├── design.md
    └── tasks.md
```

要件定義の全体像は [`docs/requirements-overview.md`](docs/requirements-overview.md)。

---

## セットアップ

```bash
docker compose up
```

※ 環境構築（M0）完了後に手順を追記する。

### チャネル変換と Qiita 公開に要る環境変数

| 変数 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | チャネル変換（Claude API）。compose はホストの値をそのまま渡す。無いと変換ジョブが `misconfigured` で失敗する |
| `TOKEN_ENCRYPTION_KEYS` | Qiita のアクセストークンを暗号化する Fernet 鍵（カンマ区切り）。**本番では必須**（無いと起動しない）。compose にはローカル専用の既知の鍵が入っている |
| `RUN_CONVERSION_WORKER` | 変換ジョブのワーカーを API と同じプロセスで動かすか（既定 `true`・ADR-0017） |

鍵の作り方：

```bash
docker compose exec backend uv run python -c \
    "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**鍵の差し替え**：新しい鍵を**先頭**に足して `TOKEN_ENCRYPTION_KEYS=新しい鍵,古い鍵` にする。古い鍵で暗号化されたトークンは、次に投稿・更新で使ったときに新しい鍵で暗号化し直される。全員のトークンが入れ替わったら古い鍵を外す（外したあとに古い鍵のままのトークンは読めなくなり、画面で再登録を求める）。

---

## 運用メモ

### Qiita に投稿できたのに、Reverb に記録が無いとき

Qiita API に二重投稿を防ぐ仕組み（冪等キー）が無いため、**Qiita への投稿が成功した直後に DB への記録が失敗する**と、Qiita に記事があるのに Reverb では未公開のままになる（publishing design.md §10-3）。起きたら次の手順で直す。

1. バックエンドのログで `qiita item ... was created but recording failed` を探し、記事 ID と URL を控える（直前の `qiita item created` の行にも同じ値が出ている）
2. Qiita 上でその記事が残っていることを確かめる
3. Reverb の画面で**もう一度投稿しない**（同じ記事が Qiita に2本できる）
4. M3 で入る「URL の貼り戻し」で、控えた URL を Qiita の公開物として登録する。それまでは Qiita 側の記事を手で消してから、Reverb からもう一度投稿する
