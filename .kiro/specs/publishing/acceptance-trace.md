# 受け入れ条件とテストの対応表（publishing・M1）

`requirements.md` §5 の **【M1】の受け入れ条件**について、どのテストが根拠になっているかを並べたもの。
【M3】の条件（C7・C9 と各節の M3 行）は対象外で、`requirements.md` でも未チェックのまま残す。

記号の意味:

| 記号 | 意味 |
|---|---|
| ✅ | 対応する自動テストがある |
| 🖐 | フロントの振る舞い。**自動テストは無く、コードと `npm run build` までで確かめた**（tasks.md 8.1 の手動確認で見る） |
| 🔶 | コード・設定では満たしているが、**落ちることを確かめるテストが無い**、または実機の確認が残っている |
| ❌ | 満たしていない、または確認できていない |

テストのパスは `backend/` 起点。`tests/modules/publishing/` を `P/` と略す。
フロントは `frontend/app/(app)/projects/[id]/contents/[cid]/` を `E/` と略す。

---

## C1. チャネルと capabilities

| 条件 | 判定 | 根拠 |
|---|---|---|
| チャネルは `publish`・`format`・`max_length` を capabilities として持つ | ✅ | `app/channels/capabilities.py`。`tests/api/test_publishing_flow.py::test_convert_edit_publish_push_and_cancel`（`/channels` の Qiita が `auto`） |
| 公開の分岐は capabilities を見て決まり、画面・Service にチャネル名での分岐を書かない | 🔶 | Service は `_require_auto`（`CAPABILITIES[ch].publish`）で分岐。画面の公開先バッジは `/channels` の表示名を使う（`E/PublishLink.tsx`）。**M1 の公開画面は Qiita のタブ固定**（`E/publish/PublishScreen.tsx` の `CHANNEL`）で、X を足すときに capabilities からタブとボタンを出し分ける |
| Qiita は `auto`。新規投稿と更新を API で行う | ✅ | `P/test_publications.py::test_publishing_records_the_publication_and_marks_published` / `test_push_updates_the_item_without_changing_the_state`、`tests/channels/test_qiita_client.py` |
| チャネル一覧を API で取得できる | ✅ | `test_publishing_flow.py::test_convert_edit_publish_push_and_cancel`、`tests/api/test_openapi.py` |

## C2. 変換プロファイル

| 条件 | 判定 | 根拠 |
|---|---|---|
| チャネルごとに変換プロファイル（構成・禁則・語尾・一人称）を DB に保持する | ✅ | `conversion_profiles`（企画×チャネル）。`P/test_conversions.py::test_request_queues_a_job_with_the_profile_and_latest_revision`（初回の変換で既定値から行ができ、内容がジョブに写る） |
| Qiita のプロファイルは言語化済みのルールを初期値として持つ | ✅ | `app/modules/publishing/profiles.py`（グローバル CLAUDE.md §5 から移植）。`test_request_queues_...`（一人称「僕」・禁則「いかがでしたか？」）、`tests/llm/test_prompts.py::test_system_prompt_lists_every_rule_of_the_profile` |
| 変換の実行履歴に、使ったプロファイルの内容（または版）が残る | ✅ | `conversion_jobs.profile_snapshot`（内容＋`version`）。`test_request_queues_...`、`ConversionJobOut.profile_snapshot` |

## C3. チャネル変換

| 条件 | 判定 | 根拠 |
|---|---|---|
| owner / editor はコンテンツとチャネルを指定して変換を実行できる | ✅ | `P/test_conversions.py::test_request_queues_...` / `test_editor_can_convert` |
| 変換は Claude API に本文とプロファイルを渡して行う | ✅ | `tests/llm/test_converter.py::test_success_returns_the_parsed_output_and_usage`（本文は user、プロファイルは system に入る）、`test_prompts.py` |
| 変換の実行はリクエストを待たせない（受け付けで応答し、状態を後から取得できる） | ✅ | 202 ＋ DB キューのワーカー（ADR-0017）。`test_publishing_flow.py::test_convert_edit_publish_push_and_cancel`（202 `queued` → ワーカー1周 → `succeeded`）、`P/test_claim_skip_locked.py` |
| 画面は変換の状態を表示し、成功したら原稿を表示する | 🖐 | `E/publish/PublishScreen.tsx`（`refetchInterval` は待機中・実行中だけ 2秒）。実サーバーでワーカーが拾うことは API のスモークテストで確認（2026-10-18・キー未設定で `misconfigured` に落ちた） |
| 失敗したとき理由が画面に出て、再実行できる | ✅ 🖐 | 理由の記録：`P/test_conversions.py::test_conversion_failures_are_recorded_with_their_code` / `test_an_unexpected_crash_does_not_leave_the_job_running`、`test_converter.py` の各失敗。画面の文言と［もう一度変換する］：`E/publish/messages.ts` |
| 同じコンテンツ・チャネルで実行中は二重に実行できない（409） | ✅ | `P/test_conversions.py::test_a_second_request_while_one_is_pending_is_409`、`P/test_db_constraints.py::test_two_active_jobs_for_the_same_channel_are_rejected`、`test_publishing_flow.py::test_error_statuses` |
| 変換の実行履歴が残り、一覧できる | ✅ | `P/test_conversions.py::test_history_is_newest_first_and_visible_to_reviewers` |
| reviewer / demo による変換は 403 | ✅ | `P/test_conversions.py::test_reviewer_and_demo_cannot_convert` |
| LLM の API キーはサーバーの環境変数で持ち、ブラウザ・レスポンス・ログに出さない | 🔶 | キーは SDK が `ANTHROPIC_API_KEY` から読み、設定クラス・レスポンス・ログに通り道が無い（`app/llm/converter.py`）。**キーが出ないことを確かめるテストは無い** |

## C4. チャネル原稿

| 条件 | 判定 | 根拠 |
|---|---|---|
| 変換が成功すると、チャネル原稿が作られる（Qiita ならタグ） | ✅ | `P/test_conversions.py::test_worker_converts_the_requested_revision_and_creates_the_draft` |
| owner / editor は原稿を編集・保存できる。楽観ロックで 409 | ✅ | `P/test_drafts.py::test_saving_marks_the_draft_as_hand_edited` / `test_saving_a_stale_version_is_409` / `test_reviewer_and_demo_cannot_edit` |
| 再変換で手直しが黙って消えない | ✅ | 置き換えずに保留し、結果を並べて選ばせる（design.md §9-2）。`P/test_conversions.py::test_reconversion_keeps_a_hand_edited_draft_and_holds_the_result`、`P/test_drafts.py::test_the_pending_result_is_shown_and_can_be_applied` / `test_applying_a_result_that_is_no_longer_pending_is_409` |
| 原稿が変換元の本文より古いことが画面で分かる | ✅ 🖐 | `P/test_drafts.py::test_the_draft_becomes_stale_only_when_the_body_changes`（状態遷移では古くならない）。表示：`PublishScreen.tsx` の警告 |
| 公開するのはチャネル原稿で、`contents.body_md` は変換・公開で書き換わらない | ✅ | `test_publishing_flow.py::test_convert_edit_publish_push_and_cancel` の最後（一連の操作のあとも `body_md` が元のまま）、`P/test_publications.py::test_publishing_records_...`（送ったのは原稿のタイトル） |
| 原稿のプレビューは HTML をサニタイズして描画する | 🖐 | content-pipeline の `MarkdownPreview`（`rehype-raw` なし）をそのまま使う |

## C5. Qiita のアクセストークン

| 条件 | 判定 | 根拠 |
|---|---|---|
| 自分のトークンを登録・差し替え・削除できる | ✅ | `P/test_accounts.py::test_register_...` / `test_registering_again_replaces_the_token` / `test_delete_removes_the_token`、`tests/api/test_qiita_account_api.py::test_register_show_and_delete` |
| アプリケーション層で暗号化して保存し、平文で保存しない | ✅ | `P/test_accounts.py::test_register_checks_with_qiita_and_stores_only_ciphertext`、`tests/core/test_crypto.py` |
| 登録後、トークンの値は API で返さない | ✅ | `test_qiita_account_api.py::test_register_show_and_delete`（PUT・GET の本文にトークンが無い） |
| 登録時に Qiita へ問い合わせ、無効なら登録しない（422） | ✅ | `P/test_accounts.py::test_a_token_qiita_rejects_is_not_stored`、`test_qiita_account_api.py::test_rejected_token_is_422` |
| トークンが無い・無効なときに公開しようとすると、理由が分かるエラーになり登録画面へ誘導される | ✅ 🖐 | `P/test_publications.py::test_without_a_token_it_is_409` / `test_qiita_errors_map_...`（401 → `qiita_token_invalid`）、`P/test_accounts.py::test_a_token_encrypted_with_a_removed_key_asks_for_re_registration`。誘導：`E/publish/messages.ts` の `TOKEN_ERRORS` で設定画面へのリンク |
| トークンはログ・例外メッセージ・エラーレスポンスに出ない | ✅ | `P/test_accounts.py::test_the_token_never_reaches_the_logs`、`test_qiita_client.py::test_status_codes_map_to_port_errors`、`test_crypto.py::test_tampered_ciphertext_is_rejected_without_leaking_values` |
| 暗号化の鍵はサーバーの環境変数で持ち、DB と別に管理する | ✅ | `TOKEN_ENCRYPTION_KEYS`。`tests/core/test_error_envelope.py::test_production_rejects_missing_token_encryption_keys`、`P/test_accounts.py::test_a_token_under_an_old_key_is_re_encrypted_on_use`（鍵の差し替え） |

## C6. Qiita への公開（auto）

| 条件 | 判定 | 根拠 |
|---|---|---|
| owner は原稿を API 経由で新規投稿できる | ✅ | `P/test_publications.py::test_publishing_records_the_publication_and_marks_published` |
| 投稿前に Qiita の制約を検証し、満たさなければ送らずに 422 | ✅ 🔶 | `P/test_publications.py::test_qiita_tag_rules_are_checked_before_sending`、`test_publishing_flow.py::test_error_statuses`。**タグ数の上限・タイトル長は API ドキュメントに記載が無く、実機の確認（tasks.md 6.8）が残っている** |
| 限定共有で投稿できる | ✅ | `test_publishing_records_...`（`private=True` で送る）、`test_publishing_flow.py`（`visibility: private`） |
| 投稿に成功すると公開物（チャネル・URL・外部 ID・日時・公開範囲）が記録される | ✅ | `test_publishing_records_...` |
| 投稿に成功すると `公開済` に遷移する（既に公開済ならそのまま） | ✅ | `test_publishing_records_...`、`tests/modules/contents/test_publish_hooks.py::test_publishing_again_keeps_the_state_without_a_log` |
| 公開済みの記事を原稿で更新できる。更新日時が残る | ✅ | `P/test_publications.py::test_push_updates_the_item_without_changing_the_state` / `test_push_keeps_the_visibility_when_omitted` |
| 送信が成功したのに記録に失敗する、を作らない | 🔶 | 二重投稿はコンテンツ行のロック＋部分 UNIQUE で防ぐ（`test_publishing_twice_is_409_and_does_not_post_again`）。**送信後の DB 障害で記録が漏れる隙間は残る**（Qiita API に冪等キーが無い）。ログに外部 ID を残し、README の手順で直す前提（design.md §10-3）。DB 障害を起こして確かめるテストは無い |
| Qiita API のエラーを種類ごとに理由が分かる形で返す | ✅ | `P/test_publications.py::test_qiita_errors_map_to_app_errors_and_nothing_is_recorded` / `test_push_to_an_item_deleted_on_qiita_is_409`、`test_qiita_client.py::test_status_codes_map_to_port_errors` |
| 同じコンテンツを Qiita に二重に新規投稿できない | ✅ | `test_publishing_twice_is_409_and_does_not_post_again`、`P/test_db_constraints.py::test_two_active_publications_for_the_same_channel_are_rejected` |
| editor / reviewer / demo による公開・更新は 403 | ✅ | `P/test_publications.py::test_only_the_owner_can_publish`、`test_publish_hooks.py::test_only_the_owner_can_lock_for_publish`（更新も同じ入口）、`test_publishing_flow.py::test_error_statuses` |

## C8. 公開物と公開取消

| 条件 | 判定 | 根拠 |
|---|---|---|
| 1つのコンテンツにチャネルごとの公開物を複数持てる | ✅ | `P/test_publications.py::test_cancel_keeps_published_while_another_channel_remains` |
| コンテンツの画面で公開物が分かる | 🖐 | `E/PublishLink.tsx`（編集・閲覧画面のヘッダのバッジ）、公開画面の「Qiita への公開」欄 |
| 企画の公開済み一覧で、コンテンツごとにどのチャネルへ出たかが分かる | ✅ | `P/test_publications.py::test_the_project_list_groups_by_content_and_hides_cancelled`。画面：`app/(app)/projects/[id]/publications/page.tsx` |
| owner は公開物を取り消せる。公開先の記事は消さないことが画面で明示される | ✅ 🖐 | `test_cancel_returns_to_drafting_and_does_not_touch_qiita` / `test_only_the_owner_can_cancel`。明示：公開取消の確認文と完了の通知 |
| 公開取消は記録として残る（誰が・いつ） | ✅ | `test_cancel_returns_...`（`cancelled_at` / `cancelled_by`）、`P/test_db_constraints.py::test_a_cancelled_publication_does_not_block_republishing`（行は残る） |
| `公開済` からの遷移を解禁する | ✅ | 公開物が0件になったら `執筆中` へ（design.md §4）。`test_cancel_returns_to_drafting_...`、`test_publish_hooks.py::test_unpublishing_goes_back_to_drafting_with_a_log` |
| `公開済` への遷移は公開操作からだけ起きる（汎用 API は 422） | ✅ | `test_publish_hooks.py::test_the_generic_transition_api_still_cannot_reach_published` |
| 他企画の公開物にはアクセスできない（404） | ✅ | `P/test_publications.py::test_cancelling_from_another_project_is_404` |

## C10. テストと品質

| 条件 | 判定 | 根拠 |
|---|---|---|
| Service 層のユニットテスト | ✅ | `P/` 一式、`test_publish_hooks.py` |
| Claude API・Qiita API はテストで実際に呼ばない（fake で成功・失敗・タイムアウト） | ✅ | `P/fakes.py`（`FakeConverter` / `FakeQiita`）、`test_converter.py`（SDK のクライアントを差し替え）、`test_qiita_client.py`（`httpx.MockTransport`・タイムアウト） |
| API の結合テスト（主経路と 401 / 403 / 404 / 409 / 422） | ✅ | `tests/api/test_publishing_flow.py`、`tests/api/test_qiita_account_api.py` |
| 新しい Service も HTTP に依存せず、MCP / ジョブから同じ認可で呼べる | ✅ | `lint-imports`（6契約。publishing の Service がポートだけを知る契約と、ジョブが Repository を叩かない契約を追加）。ワーカーは依頼した人として同じ認可を通る（`test_a_requester_who_lost_access_fails_the_job`） |
| `ruff` / `mypy` / `lint-imports` / `lint` / `tsc` / `build` が CI で緑 | 🔶 | **ローカルでは全部緑**（pytest 356）。CI の結果は `gh` の認証が切れていて確認できていない |
| 手動確認（M1 の判定） | ❌ | **未実施。** 実際の Qiita トークンと Anthropic の API キーが要る（tasks.md 6.8 / 8.1） |

---

## 集計

- 【M1】の条件 53 項目：✅ 40、✅＋🖐 4、✅＋🔶 1、🖐 3、🔶 4、❌ 1
- 残っているもの：手動確認（8.1）と Qiita の実機確認（6.8）。どちらも外部の本物のアカウントを使うので、本人が行う
