# structure.md — 構造ステアリング

## ディレクトリ構造

```
Reverb/
├── .kiro/
│   ├── steering/              プロジェクト全体のルール（本ファイル群）
│   │   ├── product.md
│   │   ├── tech.md
│   │   └── structure.md
│   └── specs/{feature}/       機能ごとの仕様
│       ├── requirements.md
│       ├── design.md
│       └── tasks.md
├── backend/                   NestJS
│   ├── src/
│   │   ├── modules/{domain}/  ドメインごとのモジュール
│   │   │   ├── *.controller.ts
│   │   │   ├── *.service.ts
│   │   │   ├── *.repository.ts
│   │   │   └── dto/
│   │   ├── channels/          チャネルアダプタ（Qiita / X / note / podcast）
│   │   ├── mcp/               MCP サーバー
│   │   ├── jobs/              BullMQ のジョブ定義・プロセッサ
│   │   └── common/            ガード・インターセプタ・フィルタ
│   └── test/
├── frontend/                  Next.js 16
│   ├── app/
│   ├── components/
│   └── lib/
├── docs/
│   ├── requirements-overview.md   プロジェクト全体の要件定義
│   └── adr/                       設計判断の記録
├── docker-compose.yml
├── CLAUDE.md
└── README.md
```

## 依存方向

```
Controller → Service → Repository → DB
```

**下位が上位を参照することは禁止。**

- チャネルアダプタは Service から呼ぶ。Controller から直接呼ばない
- ジョブのプロセッサは Service を呼ぶ。Repository を直接叩かない
- MCP サーバーは **Service 層を経由する**。専用の抜け道を作らない（認可を二重実装しないため）
- **Service は Request / Response を知らない**

理由の詳細は `docs/adr/0009-layered-architecture.md`。

## 命名規則

| 対象 | 規則 | 例 |
|---|---|---|
| ディレクトリ | kebab-case | `content-pipeline` |
| ファイル（backend） | `*.controller.ts` / `*.service.ts` / `*.repository.ts` | `contents.service.ts` |
| クラス | PascalCase | `ContentsService` |
| DB テーブル | snake_case・複数形 | `metric_snapshots` |
| DB カラム | snake_case | `published_at` |
| 中間テーブル | 単数形をアンダースコアで連結（アルファベット順） | `content_tags` |
| 環境変数 | UPPER_SNAKE_CASE | `QIITA_ACCESS_TOKEN` |
| ADR | `NNNN-kebab-title.md` | `0001-why-nestjs.md` |

## 主要なテーブルと関係

```
users
  └─ project_members ── projects              企画＝共有単位
        role: owner / editor / reviewer

contents                                       受信箱〜公開まで状態遷移
  status: 受信箱 → 採用 → 執筆中 → レビュー中 → 公開済 → 見送り
    ├─ content_revisions                       履歴
    ├─ content_tags ── tags                    多対多
    ├─ review_comments                         行アンカー・リアルタイム反映
    ├─ section_locks                           誰が今どこを編集中か
    └─ publications                            公開先チャネルごと
          └─ metric_snapshots                  日次・50万行

channels / channel_accounts / ingest_jobs / job_runs
```

**設計の肝は `contents 1 : n publications`。** 1つのネタが複数チャネルに出せることが、チャネル横断分析の土台になる。

## スペックの分割単位

`.kiro/specs/{feature}/` の `{feature}` は、`docs/requirements-overview.md` のエピック（E1〜E9）に対応させる。1スペックは概ね 20〜60h の粒度に収める。

## 言語

- **思考・推論は英語**、**ユーザーへの返答は日本語**
- リポジトリに書き込む Markdown（steering / specs / ADR / README）は**日本語**
- コード内のコメント・識別子は**英語**
