# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Reverb

**「書いたあとに何が起きたか」を記録し続けるための箱。**
Obsidian の断片ノートから、記事ネタ・執筆・レビュー・公開を経て、反応の日次追跡までを1本のパイプラインにする発信オペレーション基盤。

個人開発プロジェクト。2026年9月〜12月の4ヶ月で Phase 1 を完成させる。

---

## Agentic SDLC — Spec-Driven Development (cc-sdd)

Kiro 流のスペック駆動開発で進める。大きな機能実装は必ず **ステアリング → 要件 → 設計 → タスク → 実装** の順で進め、各フェーズで人間のレビューを挟む。

### パス

| 種別 | パス |
|------|------|
| ステアリング（プロジェクト全体ルール） | `.kiro/steering/` |
| スペック（機能ごとの仕様） | `.kiro/specs/{feature}/` |
| プロジェクト全体の要件定義 | `docs/requirements-overview.md` |
| 設計判断の記録（ADR） | `docs/adr/` |

### ステアリングの読み込み

**会話開始時に必ず以下3ファイルを読み込み、内容をプロジェクト知識として保持すること。**

- `.kiro/steering/product.md` — プロダクトの目的・ユーザー・扱う技術領域・削ってはいけないもの
- `.kiro/steering/tech.md` — 技術スタック・アーキテクチャ決定・開発標準
- `.kiro/steering/structure.md` — ディレクトリ構造・命名規則・依存方向

ステアリングに変更が必要になった場合は、実装前に対象ファイルを更新する。

### ワークフロー

**Phase 1: スペック作成（Requirements → Design → Tasks）**

**各ステップで必ず人間のレビューと承認を得てから次に進む。`-y` フラグが指定された場合のみ承認をスキップしてよい。**

1. `requirements.md` — ユーザーストーリー（As a / I want / So that）＋ チェッカブルな受け入れ条件
2. `design.md` — コンポーネント設計・API 設計・データモデル・シーケンス
3. `tasks.md` — 実装タスクのチェックリスト（`- [ ] 1. タスク名`）

**Phase 2: 実装**

- `TaskCreate` で各タスクを登録し、着手時に `in_progress`、完了時に `completed` へ更新
- `tasks.md` のチェックボックスも同時に更新（`- [x]`）
- **1サブタスク完了ごとにコミット**し、ユーザーにプッシュを促す

### 実装検証

実装完了後は `/code-review` でコードレビューを実施し、`requirements.md` の受け入れ条件との整合を確認する。

---

## 開発ルール

### 言語

- **思考・推論は英語**で行う
- **ユーザーへの返答は日本語**で行う
- リポジトリに書き込む Markdown（steering / specs / ADR / README）は**日本語**
- コード内のコメント・識別子は**英語**

### Git ルール

- 原則として `main` ブランチで直接開発する（トランクベース開発）
- コミットはサブタスク完了ごとにこまめに行う（Completion over Perfection）
- 「コミットプッシュして」と指示された場合、`git add` / `git commit` / `git push` は確認なしで実行する
- `--force` push・`reset --hard`・ブランチ削除など破壊的操作は必ず事前確認する
- 既存コミットの amend や履歴書き換えは、明示的に指示された場合のみ

### 自律的な実行

指示のスコープ内では自律的に動く。必要なコンテキストを自ら収集し、今回の実行内で作業を完結させる。本質的な情報が欠けている場合、または指示が致命的に曖昧な場合のみ質問する。

---

## 【重要】この2つは記憶で書かない

### Next.js 16

**トレーニングデータ上の慣習と異なる破壊的変更を含む。**
コードを書く前に `frontend/node_modules/next/dist/docs/` を参照すること。

### Claude API

Claude API を呼ぶコードを書く前に、**`/claude-api` スキルを読むこと。**
モデル ID・パラメータ・SDK の使い方は 2025〜2026 に破壊的変更が複数入っている。

---

## アーキテクチャの要点

**スタックは Python / FastAPI × Next.js 16。** バックエンドは NestJS から変更済み（ADR-0012）。

**依存方向**：`Controller → Service → Repository`。下位が上位を参照することは禁止。
**FastAPI は層構造を強制しない**ため、`.importlinter` の契約を CI で検証して守る。

**共同編集に Yjs（CRDT）を使わない。** セクション単位の編集ロックと楽観ロックを自前で設計する（バックエンドの設計を成果物として残すため）。

**Markdown エディタは既製品を組み込むだけ。自作しない。**

**MCP サーバーは Service 層を経由する。** 認可を二重実装しないため、専用の抜け道を作らない。

**Obsidian Vault へはサービスから一切アクセスしない。** Vault はローカルにあり AWS からは物理的に到達できない。Vault を読むのはローカルの Claude Code の役割。

---

## よく使うコマンド

```bash
# 全サービス起動
docker compose up

# バックエンド（コンテナ内・Python / FastAPI）
docker compose exec backend pytest
docker compose exec backend ruff check .
docker compose exec backend mypy .
docker compose exec backend lint-imports   # 層の依存契約

# フロントエンド（コンテナ内）
docker compose exec frontend npm run lint
docker compose exec frontend npm run build
```

※ 環境構築（M0）完了後に実際のコマンドへ更新すること。
