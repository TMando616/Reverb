# tasks.md — content-pipeline（ネタ管理・執筆）

> **前提**：`requirements.md` / `design.md` / ADR-0016 はレビュー待ち（承認後に着手）。
> **見積り**：約 40h（M1 のエディタ 30h ＋ タグ・カンバン 10h）。M1 の残り（チャネル変換・Qiita 公開 22h）は `publishing`。
> **進め方**：M1 の判定は「縦に1本通す」。**バックエンド → 画面の順に、機能ごとに縦に通す**（タグ → 絞り込み → リビジョン → 編集画面）。
> モジュール単位で Service / Repository のユニットテストを併走させる（`design.md` §11）。
> **1サブタスク完了ごとにコミット**し、ユーザーにプッシュを促す。

## 0. スパイク：データフェッチ層の採否（ADR-0015 の宿題 / `design.md` §9-1）

**ADR-0015 が「`content-pipeline` の tasks.md の先頭に置く」と決めたタスク。** 本実装の前に、捨てる前提のコードで確かめる。

- [x] 0.1 `@tanstack/react-query` を入れ、Next.js 16 の docs（`02-guides/client-side-data-fetching/tanstack-query.md`）どおりに Provider と `HydrationBoundary` を置く
- [x] 0.2 検証①：別タブから `BroadcastChannel` で送ったメッセージを `setQueryData` で反映し、`useQuery` を読む表示が更新される
- [x] 0.3 検証②：①の更新が来ても、テキストエリアの編集中バッファ（`useState`）が上書きされない
- [x] 0.4 検証③：Server Component からの初期データとミューテーション後のキャッシュが二重管理にならない（ミューテーション → 表示が1回で正しく変わる）
- [x] 0.5 結果を ADR-0015 に追記（採用 / 不採用と理由）。スパイクのコードは消す。不採用なら `design.md` §9-5 を書き換えてから先へ進む

## 1. データモデルとマイグレーション（C1 / C4 / C7）

- [x] 1.1 `contents/models.py`：`Content.source_note_path`（`String(500)` nullable）、`UNIQUE (id, project_id)`
- [x] 1.2 `Tag`（`project_id` / `name` / `name_key` / `UNIQUE (project_id, name_key)` / `UNIQUE (id, project_id)`）、`ContentTag`（`project_id` / `content_id` / `tag_id`・複合 FK 2本・`ix_content_tags_tag_id`）。`Content.tags` relationship は `lazy="raise"`（`design.md` §3-3・§6-5）
- [x] 1.3 `ContentRevision`（`revision_no` / `title` / `body_md` / `kind` CHECK / `restored_from_no` / `created_by`・`UNIQUE (content_id, revision_no)`）
- [x] 1.4 マイグレーション生成 → **複合 FK と UNIQUE を目視**（autogenerate が複合 FK を取りこぼしていないか）→ 既存コンテンツの初版（`kind = create`）を作るデータ移行を手で足す → `upgrade head` / `downgrade -1` / `upgrade head` が通る
- [x] 1.5 DB 制約のテスト：他企画のタグを `content_tags` に直接 INSERT すると IntegrityError（`design.md` §11）

## 2. タグ（C1）

- [x] 2.1 `TagRepository`：一覧（名前順・使用件数付き）/ `name_key` 検索 / 作成 / 改名 / 削除 / 「この企画の ID か」の一括確認。UNIQUE 違反 → `TagNameConflictError`（409）にマッピング
- [x] 2.2 `core/exceptions.py`：`TagNameConflictError`（409・`tag_name_conflict`）、`InvalidTagError`（422・`invalid_tag`）。例外ハンドラに登録
- [x] 2.3 `TagService`：`list`（VIEW）/ `create` / `rename` / `delete`（WRITE）。名前の正規化（NFKC → casefold → strip）と 1〜50 文字
- [x] 2.4 `ContentService.set_tags`（WRITE / 企画外 ID・11 個以上は 422 / 差分で INSERT・DELETE / `version` は触らない）。`create` に `tag_ids` を足す
- [x] 2.5 ルーター：`GET/POST /projects/{id}/tags`、`PATCH/DELETE /projects/{id}/tags/{tag_id}`、`PUT /projects/{id}/contents/{cid}/tags`。詳細・一覧のレスポンスに `tags`
- [x] 2.6 ユニットテスト：同名（大文字小文字・全角半角）409 ／他企画タグ 422 ／11 個目 422 ／改名の反映 ／削除でコンテンツは残る ／reviewer・demo 403

## 3. 絞り込みと元ノート（C3 / C4）

- [x] 3.1 `ContentRepository.list`：`statuses` / `tag_ids`（AND・`HAVING COUNT(DISTINCT)`）/ `q`（`ILIKE`・`%` `_` `\` をエスケープ）/ `selectinload(Content.tags)` / 最終更新順（`design.md` §6-5）
- [x] 3.2 ルーター：`GET .../contents?tag=&tag=&status=&status=&q=`（`q` は 1〜100 文字）
- [x] 3.3 `source_note_path` のバリデータ（絶対パス・ドライブ・`..`・制御文字を 422 / `\` → `/` 正規化）。`POST` / `PATCH` で受け、`PATCH` は「省略」と `null` を `model_fields_set` で区別
- [x] 3.4 ユニットテスト：タグ AND ／状態複数 ／キーワードがタイトル・本文に効く ／`%` `_` を含むキーワード ／他企画が混ざらない ／パスの検証パターン

## 4. リビジョンと復元（C6 / C7）

- [x] 4.1 `RevisionRepository`：`append`（`MAX + 1`・UNIQUE 違反は 409）/ 一覧（新しい順・`before` / `limit`・本文なし・`body_length`）/ 単体取得（コンテンツ経由で企画スコープ）
- [x] 4.2 `ContentService.create` で初版、`update` で本文が変わったときだけ flush の**後**に1件（`design.md` §6-2）
- [x] 4.3 `ContentService.restore`（WRITE / version 照合 / 同内容なら何もしない / `kind = restore` で1件）
- [x] 4.4 ルーター：`GET .../revisions`、`GET .../revisions/{no}`、`POST .../revisions/{no}/restore`
- [x] 4.5 ユニットテスト：`design.md` §11 のリビジョン・復元の行をすべて
- [x] 4.6 API 結合テスト：主経路（タグ作成 → タグ付き作成 → 絞り込み → 保存2回 → 版一覧3件 → 1版目を復元 → 4件）とエラー系統（`version_conflict` / `tag_name_conflict` / `invalid_tag` / `validation_error`）
- [x] 4.7 `ruff` / `mypy` / `lint-imports` / `pytest` 緑

## 5. フロントの土台（`design.md` §9-9 / §9-10）

- [x] 5.1 `openapi-typescript` で `frontend/types/api.ts` を生成する npm スクリプト。生成物をコミット
- [x] 5.2 `lib/api/types.ts` を生成物から引く形に置き換え（別名・日本語ラベル・`ALLOWED_TRANSITIONS` は残す）
- [x] 5.3 CI に「型を生成し直して差分が出たら落とす」を追加
- [x] 5.4 `radix-ui` を導入し、`components/ui/` に Menu / Dialog / 複数選択の最小部品（ドメインを知らない）

## 6. カンバンと絞り込み（C2 / C3）

- [x] 6.1 `/projects/[id]` を `searchParams` を読んで API に渡す Server Component に変更。タグ一覧も取得
- [x] 6.2 `KanbanBoard`（Client）：6列・横スクロール・状態で絞り込んだら選んだ列だけ。カードにタイトル・タグ・最終更新
- [x] 6.3 カードの移動メニュー：`ALLOWED_TRANSITIONS` の先だけ表示 ／`useOptimistic` ＋ 既存の Server Action ／失敗で元の列へ戻り理由を表示 ／reviewer・demo にはメニューを出さない
- [x] 6.4 絞り込みバー（タグ複数・状態複数・キーワード 300ms）→ URL を更新
- [x] 6.5 新規ネタ登録ダイアログ（タイトル・タグ複数＋その場で作成・メモ → `body_md`）
- [x] 6.6 `/projects/[id]/tags`：一覧・改名・削除（409 の表示）
- [x] 6.7 手動確認：カンバンで移動・失敗時の戻り・絞り込みのリロード / URL 共有

## 7. 編集画面（C5 / C6 / C8）

- [x] 7.1 `/projects/[id]/contents/[cid]`：Server Component で取得し、role で編集画面／閲覧画面を出し分け（`design.md` §9-2）
- [x] 7.2 CodeMirror 6 の組み込み（`@uiw/react-codemirror` ＋ `@codemirror/lang-markdown`・`next/dynamic` の `ssr: false`）。作法は Next.js 16 の docs を見て確定
- [x] 7.3 プレビュー（`react-markdown` ＋ `remark-gfm`・**`rehype-raw` なし**）と表示切り替え（編集／並べて／プレビュー）
- [x] 7.4 文字数（`Intl.Segmenter`・改行除く・数え方の併記）
- [x] 7.5 自動保存：5 秒停止で発火 ／1つずつ直列 ／`Cmd/Ctrl + S` ／5 つの保存状態表示 ／失敗時 10 秒後に1回再試行
- [x] 7.6 409 の扱い：自動保存停止・バッファ保持・[自分の内容をコピー] / [最新を読み込む]
- [x] 7.7 未保存で離脱するときの警告（`beforeunload` ＋ アプリ内リンク）
- [x] 7.8 タグ・元ノートの編集（即保存・返ってきた `version` をエディタ側へ反映）
- [x] 7.9 閲覧画面（reviewer / demo）：プレビューと文字数のみ。本文に `<script>` や `javascript:` リンクを入れて実行されないことを確認
- [x] 7.10 カンバンのカードから編集／閲覧画面への導線

## 8. リビジョンパネル（C7）

- [x] 8.1 版の一覧（50件ずつ・保存した人はメンバー一覧から引く・種類と文字数）
- [x] 8.2 版のプレビュー（ダイアログ・本文はこのとき取得）
- [x] 8.3 [この版に戻す]：未保存の変更があれば確認 → 復元 → バッファと version を置き換え ／reviewer・demo には出さない

## 9. 仕上げ

- [x] 9.1 手動確認（M1 前半の判定）：**ネタを登録 → タグを付ける → カンバンで「執筆中」へ → 書く（自動保存）→ 版を戻す**が通る。別タブで同時に保存して 409 のバナーが出る
- [ ] 9.2 `requirements.md` の受け入れ条件 C1〜C9 にチェックを入れ、テストとの対応を `acceptance-trace.md` に残す
- [ ] 9.3 steering / `requirements-overview.md` §13 / CLAUDE.md（コマンドが増えた場合）を更新
- [ ] 9.4 `/code-review` を実施し、指摘を修正

---

## 完了の定義

- `requirements.md` §5 の受け入れ条件 C1〜C9 のチェックボックスをすべて満たす
- `/code-review` を実施し、`requirements.md` との整合を確認する（`CLAUDE.md`「実装検証」）
- **`publishing` が「`body_md` を受け取って Qiita 体裁に変換する」ところから始められる状態になっている**
