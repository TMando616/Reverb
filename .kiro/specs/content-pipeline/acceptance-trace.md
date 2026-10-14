# 受け入れ条件とテストの対応表（content-pipeline）

`requirements.md` §5 の受け入れ条件65項目について、**どのテストが根拠になっているか**を並べたもの。
`requirements.md` のチェックボックスを埋める前の突き合わせ資料。

記号の意味:

| 記号 | 意味 |
|---|---|
| ✅ | 対応する自動テストがある |
| 🖐 | フロントの振る舞い。**自動テストは無く、tasks.md 9.1 の手動確認とコードで確かめた** |
| 🔶 | コード・設定では満たしているが、**落ちることを確かめるテストが無い** |
| ❌ | 満たしていない、または確認できていない |

テストのパスは `backend/` 起点、フロントのパスは `frontend/` 起点。
`app/(app)/projects/[id]/` を `P/`、その下の `contents/[cid]/` を `E/` と略す。

---

## C1. タグ

| 条件 | 判定 | 根拠 |
|---|---|---|
| owner / editor は企画内にタグを作成できる（名前必須） | ✅ | `tests/modules/contents/test_tags.py` の各テスト（editor での作成を含む）、`tests/api/test_content_pipeline_flow.py::test_tag_write_filter_save_and_restore` |
| 同じ企画内で同名のタグは作れない | ✅ | `test_tags.py::test_name_key_folds_case_width_and_surrounding_spaces` / `test_same_name_in_another_spelling_conflicts`、`test_content_pipeline_flow.py::test_new_error_codes`（409 `tag_name_conflict`） |
| 別の企画のタグをコンテンツに付けられない | ✅ | `test_tags.py::test_tags_of_another_project_are_rejected`、`test_content_tag_constraints.py::test_cross_project_tagging_is_rejected_by_the_database`（DB の複合 FK でも拒否） |
| 改名が付与済みのコンテンツすべてに反映される | ✅ | `test_tags.py::test_rename_is_reflected_on_every_tagged_content` |
| 削除するとすべてのコンテンツから外れる（コンテンツは残る） | ✅ | `test_tags.py::test_delete_untags_contents_but_keeps_them` |
| 多対多 | ✅ | `test_tags.py::test_list_counts_usage`（1タグ↔複数コンテンツ）、`test_set_tags_replaces_the_set`（1コンテンツ↔複数タグ） |
| 同じタグを二重に付けられない | ✅ | `test_tags.py::test_same_tag_twice_is_attached_once`（2026-10-18 追加）。DB 側は `content_tags` の複合主キー |
| 取得・一覧で付いているタグが分かる | ✅ | `test_content_pipeline_flow.py::test_tag_write_filter_save_and_restore`（作成レスポンスと一覧の `tags`。一覧側は 2026-10-18 追加） |
| reviewer / demo の作成・改名・削除・付け外しは 403 | ✅ | `test_tags.py::test_reviewer_and_demo_cannot_change_tags` |

## C2. カンバン

| 条件 | 判定 | 根拠 |
|---|---|---|
| 6状態を列にしたカンバン（遷移の流れ順） | 🖐 | `P/KanbanBoard.tsx` |
| カードにタイトル・タグ・最終更新日時 | 🖐 | `P/ContentRow.tsx` |
| owner / editor はカンバン上から状態を変更できる（メニュー方式） | 🖐 | `P/KanbanBoard.tsx`・`P/actions.ts`。9.1 で「執筆中」への移動を確認 |
| 遷移できない先は選べない | 🖐 | `P/KanbanBoard.tsx`（許可された遷移先だけをメニューに出す）。防御は foundation の 422（`test_content_transition.py::test_disallowed_transition_is_422_and_changes_nothing`） |
| API に拒否されたらカードは元の列に戻り、理由が出る | 🖐 | `P/KanbanBoard.tsx`（失敗時はキャッシュを戻してエラーを表示） |
| reviewer / demo には状態変更の操作が出ない | 🖐 | `P/KanbanBoard.tsx` の `canWrite`。API 側の 403 は `test_content_transition.py::test_reviewer_and_demo_cannot_transition` |
| カードから編集画面（reviewer / demo は閲覧画面）へ移動できる | 🖐 | `P/ContentRow.tsx`、`E/page.tsx`（ロールで `ContentEditor` / `ContentViewer` を出し分け） |
| カンバンから新しいネタを登録できる（タイトル・タグ・メモ） | 🖐 | `P/NewContentDialog.tsx`・`P/CreateContentForm.tsx`。9.1 で確認 |

## C3. 絞り込み

| 条件 | 判定 | 根拠 |
|---|---|---|
| 一覧 API はタグ・状態・キーワードで絞り込める | ✅ | `test_content_filters.py` 全体、`test_content_pipeline_flow.py::test_tag_write_filter_save_and_restore` |
| タグは複数指定で AND | ✅ | `test_content_filters.py::test_tags_are_and_ed` |
| 状態は複数指定できる | ✅ | `test_content_filters.py::test_statuses_are_or_ed` |
| キーワードはタイトルと本文の部分一致 | ✅ | `test_content_filters.py::test_keyword_matches_title_or_body_case_insensitively` / `test_like_wildcards_in_keyword_are_literal` |
| 条件を組み合わせられる | ✅ | `test_content_filters.py::test_filters_combine_and_stay_in_the_project` |
| 企画スコープの中だけで効く | ✅ | 同上、`test_content_repository.py::test_list_is_scoped_and_filters_status_and_deleted` |
| 一覧 API は本文全体を返さない | ✅ | `test_content_pipeline_flow.py::test_tag_write_filter_save_and_restore`（`body_md` が無いことを確認） |
| 画面の絞り込み条件が URL に残る | 🖐 | `P/FilterBar.tsx`（`router.replace` でクエリに書く）・`P/page.tsx`（`searchParams` から復元） |

## C4. 元ノートのパス

| 条件 | 判定 | 根拠 |
|---|---|---|
| 任意項目として `source_note_path` を持てる | ✅ | `test_content_filters.py::test_source_note_path_is_kept_and_cleared` |
| 作成時・更新時に設定・変更・削除できる | ✅ | 同上、`test_content_filters.py::test_update_distinguishes_omitted_from_null` |
| 絶対パス・`..` を含むものは 422 | ✅ | `test_content_filters.py::test_invalid_source_note_paths_are_rejected`、`test_content_pipeline_flow.py::test_new_error_codes` |
| サービスはこのパスのファイルを読まない・存在確認もしない | 🔶 | `ContentService` はパスの文字列検証だけで、ファイル I/O を持たない。**「読まない」ことを確かめるテストは無い**（後述） |
| 編集画面・閲覧画面で元ノートのパスが表示される | 🖐 | `E/ContentEditor.tsx`（編集欄）、`E/ContentViewer.tsx` |
| 将来 MCP から同じ Service を通して設定できる | 🔶 | `ContentService.create` / `update` が `source_note_path` を引数で受ける。HTTP 非依存は `lint-imports` の `Service は FastAPI を知らない` 契約で担保 |

## C5. エディタと編集画面

| 条件 | 判定 | 根拠 |
|---|---|---|
| 既製の Markdown エディタを組み込む（選定は ADR） | 🖐 | CodeMirror 6（`E/CodeMirrorField.tsx`）。選定は `docs/adr/0016-markdown-editor.md` |
| 編集画面でタイトルと本文を編集できる | 🖐 | `E/ContentEditor.tsx`。9.1 で確認 |
| 編集画面からタグと `source_note_path` を編集できる | 🖐 | `E/ContentEditor.tsx` |
| エディタはクライアントに閉じ、初期データ取得はサーバー側 | 🖐 | `E/page.tsx`（Server Component で取得）→ `E/ContentEditor.tsx`（`"use client"`） |
| 編集中バッファはクライアント状態で、キャッシュを直接書き換えない | 🖐 | `E/use-content-writer.ts`（バッファと保存済みの `version` を別に持つ） |
| reviewer / demo は閲覧画面になる（API でも 403） | 🖐 | `E/page.tsx` → `E/ContentViewer.tsx`。API 側は `test_content_service.py::test_reviewer_and_demo_cannot_write` |

## C6. 自動保存と競合検出

| 条件 | 判定 | 根拠 |
|---|---|---|
| 編集が止まってから一定時間で自動保存 | 🖐 | `E/use-content-writer.ts`（`AUTOSAVE_DELAY_MS = 5_000`）。9.1 で確認 |
| 手動でも保存できる | 🖐 | `E/ContentEditor.tsx`（⌘S / Ctrl+S とボタン） |
| 保存状態が画面に表示される | 🖐 | `E/ContentEditor.tsx`・`E/use-content-writer.ts` |
| 読み込み時の `version` を添え、他で更新されていれば 409 | ✅ | `test_content_service.py::test_stale_expected_version_is_409_and_changes_nothing` / `test_conflict_detected_at_flush_is_409`、`test_content_pipeline_flow.py::test_new_error_codes` |
| 409 で自動保存を止め、バッファを失わず「他で更新された」を表示 | 🖐 | `E/use-content-writer.ts`。9.1 で別タブ同時保存 → 409 バナーを確認 |
| 通信エラー等でバッファを失わず再試行できる | 🖐 | `E/use-content-writer.ts`（`RETRY_DELAY_MS` で再試行） |
| 未保存のまま離れようとすると警告 | 🖐 | `E/use-leave-guard.ts`（`beforeunload` ＋ アプリ内リンク） |
| 本文が変わらない保存は `version` を進めずリビジョンも作らない | ✅ | `test_revisions.py::test_unchanged_save_keeps_version_and_revisions`、`test_content_service.py::test_unchanged_patch_keeps_version_without_breaking_conflict_detection` |

## C7. リビジョン

| 条件 | 判定 | 根拠 |
|---|---|---|
| 本文が変わる保存のたびにリビジョンが1件 | ✅ | `test_revisions.py::test_create_makes_the_first_revision` / `test_each_changing_save_appends_one_revision` |
| 保存した人・日時・タイトルと本文全体が残る | ✅ | `test_revisions.py::test_create_makes_the_first_revision`（`created_by` / `title` / `body_md`） |
| 追記専用で、更新・削除の API を持たない | ✅ | `tests/api/test_openapi.py::test_openapi_lists_every_endpoint`（エンドポイントを等号で固定） |
| 新しい順に一覧できる（本文全体を返さない） | ✅ | `test_revisions.py::test_list_pages_with_before_and_reports_length`、`test_content_pipeline_flow.py::test_tag_write_filter_save_and_restore` |
| 任意のリビジョンの本文を閲覧できる | ✅ | `test_content_pipeline_flow.py::test_tag_write_filter_save_and_restore`（`/revisions/1` の `body_md`） |
| owner / editor は任意のリビジョンへ復元できる | ✅ | `test_revisions.py::test_restore_appends_a_new_revision_with_the_old_text` |
| 復元は新しいリビジョンを1件作る | ✅ | 同上、`test_content_pipeline_flow.py`（最新が `restore`・`restored_from_no = 1`） |
| 古い `version` での復元は 409 | ✅ | `test_revisions.py::test_restore_with_a_stale_version_conflicts` |
| 他企画のリビジョンにはアクセスできない | ✅ | `test_revisions.py::test_revisions_of_another_project_are_not_found` / `test_missing_revision_is_not_found` |
| 状態遷移・タグ・`source_note_path` の変更ではリビジョンを作らない | ✅ | `test_revisions.py::test_non_body_changes_make_no_revision` |

## C8. プレビューと文字数

| 条件 | 判定 | 根拠 |
|---|---|---|
| 本文の Markdown をプレビュー表示できる | 🖐 | `components/contents/MarkdownPreview.tsx` |
| HTML をサニタイズしてから描画する | 🔶 | `react-markdown` に `rehype-raw` を入れていないため、本文中の HTML はタグとして解釈されない。**`<script>` を入れて実行されないことを確かめるテストは無い** |
| 文字数がリアルタイムに表示される | 🖐 | `components/contents/char-count.ts`・`E/ContentEditor.tsx` |
| 数え方を決め、画面上で分かるようにする | 🖐 | `char-count.ts`（`CHAR_COUNT_NOTE = "記法込み・改行除く"`）。決定は `design.md` §8 |
| 閲覧画面でもプレビューと文字数を見られる | 🖐 | `E/ContentViewer.tsx` |

## C9. テストと品質

| 条件 | 判定 | 根拠 |
|---|---|---|
| Service 層のユニットテスト | ✅ | `tests/modules/contents/test_tags.py` / `test_content_filters.py` / `test_revisions.py` / `test_content_service.py` |
| Repository 層のユニットテスト（タグ AND・キーワード・企画スコープ） | ✅ | `test_content_filters.py` は**本物の Repository**で Service を組み立てる（`conftest.py` の `world`）。スコープは `test_content_repository.py` |
| API の結合テスト（主経路と 401 / 403 / 404 / 409 / 422） | ✅ | `test_content_pipeline_flow.py` の3本（403 の系統は foundation の `tests/api/test_error_statuses.py`） |
| 新しい Service も HTTP 非依存（`lint-imports` が緑） | ✅ | `lint-imports`：4 kept, 0 broken（2026-10-18 ローカル実行） |
| `ruff` / `mypy` / `lint-imports` / `lint` / `tsc` / `build` が緑 | ✅ | 2026-10-18 にローカルで全て通過。CI の同じジョブ（`.github/workflows/`）で走る |

---

## 集計

| 判定 | 件数 |
|---|---|
| ✅ 対応テストあり | 36 |
| 🖐 フロント・手動確認 | 26 |
| 🔶 実装では満たすがテストが無い | 3 |
| ❌ 満たしていない | 0 |

（2026-10-18 集計。`/code-review` の指摘対応を含めて pytest 206 件）

### 🖐 が多い理由

フロントの自動テスト（コンポーネントテスト・E2E）は Phase 1 で置かない判断をしている。
**認可・楽観ロック・リビジョン記録といった壊れると困る判断はすべて API 側にあり、そちらは ✅ で押さえてある。**
フロントに残るのは表示と操作の配線なので、9.1 の手動確認（ネタ登録 → タグ → 執筆中 → 自動保存 → 版を戻す → 409 バナー）でまとめて見た。

### 残る 🔶 3件（テストにしない判断）

- **サービスが Vault のファイルを読まない**（C4）。「読まない」ことは書けるテストが無い。
  `ContentService` にファイル I/O が無いことをレビューで見る
- **MCP から同じ Service で設定できる**（C4）。`mcp-server` スペックで実際に呼ぶときに確かめる
- **プレビューのサニタイズ**（C8）。`rehype-raw` を入れないことが本体。
  フロントのテスト基盤を入れるときに、`<script>` が文字として出ることを最初のテストにする
