# 受け入れ条件とテストの対応表（foundation）

`requirements.md` §5 の受け入れ条件63項目について、**どのテストが根拠になっているか**を並べたもの。
`requirements.md` のチェックボックスを埋める前の突き合わせ資料。

記号の意味:

| 記号 | 意味 |
|---|---|
| ✅ | 対応するテストがある |
| 🔶 | コード・設定では満たしているが、**落ちることを確かめるテストが無い** |
| ❌ | 満たしていない、または確認できていない |

テストのパスは `backend/` 起点。

---

## F1. ログインとセッション

| 条件 | 判定 | 根拠 |
|---|---|---|
| 正しい email + password でログインでき、トークンが発行される | ✅ | `tests/modules/auth/test_service.py::test_login_success_stores_only_the_token_hash_and_a_14_day_expiry`、`tests/api/test_main_path.py::test_login_create_project_content_and_move_to_drafting` |
| 誤った資格情報では 401、トークンは発行されない | ✅ | `tests/modules/auth/test_service.py::test_login_with_wrong_password_is_401` |
| パスワードはハッシュ化して保存される | ✅ | `tests/core/test_security.py::test_hash_password_roundtrip` |
| トークンを付与したリクエストで保護 API にアクセスできる | ✅ | `tests/modules/auth/test_deps.py::test_valid_token_resolves_to_an_actor`、`tests/api/test_main_path.py` の主経路 |
| トークンが無い／不正／期限切れは 401 | ✅ | `tests/modules/auth/test_deps.py::test_missing_header_is_401_not_422` / `test_malformed_header_is_401` / `test_unknown_or_revoked_or_expired_token_is_401`、`tests/api/test_error_statuses.py::test_401_without_a_token` / `test_401_with_a_garbage_token` |
| ログアウトすると以後 401 | ✅ | `tests/modules/auth/test_service.py::test_logout_revokes_the_hashed_token`、`tests/api/test_main_path.py::test_logout_revokes_the_token` |
| トークンには有効期限がある | ✅ | `tests/modules/auth/test_service.py::test_login_success_stores_only_the_token_hash_and_a_14_day_expiry` |

## F2. 招待制ユーザー管理

| 条件 | 判定 | 根拠 |
|---|---|---|
| 自己登録エンドポイントが存在しない | ✅ | `tests/api/test_openapi.py::test_openapi_lists_every_endpoint`（公開エンドポイントを等号で固定しているので、登録 API を足せば落ちる） |
| owner は招待を発行できる | ✅ | `tests/modules/projects/test_member_service.py::test_invite_stores_only_the_token_hash_and_returns_the_path` |
| 招待発行時にロールを指定する | ✅ | 同上＋`test_logged_in_user_is_added_with_the_invitation_role` |
| 受諾したユーザーが指定ロールで追加される | ✅ | `tests/modules/projects/test_invitation_service.py::test_logged_in_user_is_added_with_the_invitation_role` |
| 未登録の宛先はフロー内でパスワードを設定して作られる | ✅ | `tests/modules/projects/test_invitation_service.py::test_anonymous_acceptance_registers_a_user_from_the_invitation_email` |
| 招待に有効期限があり、期限切れは受諾できない | ✅ | `tests/modules/projects/test_invitation_service.py::test_expired_invitation_is_404` |
| 重複メンバーシップは作られない | ✅ | `tests/modules/projects/test_invitation_service.py::test_existing_member_keeps_their_role_when_accepting_a_different_one` |
| owner はロール変更・除名ができる | ✅ | `tests/modules/projects/test_member_service.py::test_demoting_an_owner_is_allowed_while_another_owner_remains`、`test_list_members_returns_a_view_per_row` |
| 最後の owner を除名／降格できない | ✅ | `tests/modules/projects/test_member_service.py::test_demoting_the_last_owner_is_forbidden` / `test_removing_the_last_owner_is_forbidden` |
| owner 以外の招待・ロール変更・除名は 403 | ✅ | `tests/modules/projects/test_member_service.py::test_non_owner_cannot_invite` / `test_non_owner_cannot_change_role` / `test_non_owner_cannot_remove` |

## F3. デモアカウント

| 条件 | 判定 | 根拠 |
|---|---|---|
| デモアカウントでログインできる | 🔶 | `is_demo` の払い出しは `app/cli.py` の `--demo`。**demo でログインして 200 になる経路のテストが無い**（`tests/api/test_error_statuses.py::test_403_when_a_demo_account_creates_a_project` はログイン自体は通っているので実質は担保） |
| 参加している企画とコンテンツを閲覧できる | ✅ | `tests/modules/projects/test_project_service.py::test_demo_member_may_still_read_a_project`、`tests/modules/contents/test_content_service.py::test_reviewer_and_demo_can_read` |
| 作成・更新・削除・遷移・招待は 403 | ✅ | `tests/modules/contents/test_content_service.py::test_reviewer_and_demo_cannot_write`、`tests/modules/contents/test_content_transition.py::test_reviewer_and_demo_cannot_transition`、`tests/modules/projects/test_project_service.py::test_demo_cannot_create_a_project`、`tests/modules/projects/test_invitation_service.py::test_logged_in_demo_cannot_accept` |
| demo であることが認可判定の中で識別できる | ✅ | `tests/core/test_authorization.py::test_demo_is_clamped_to_view_only_intersection` / `test_require_not_demo_blocks_demo` |

**穴**: demo による**招待の発行**（`invite`）が 403 になることのテストが無い。`require_not_demo` ではなく `VIEW_ONLY` の積集合で弾かれる経路なので、確認しておきたい。

## F4. 企画とメンバー

| 条件 | 判定 | 根拠 |
|---|---|---|
| 企画を作成でき、作成者が owner になる | ✅ | `tests/modules/projects/test_project_service.py::test_create_enrols_the_creator_as_owner` |
| 自分がメンバーの企画のみ一覧・取得できる | ✅ | `tests/modules/projects/test_project_service.py::test_list_mine_returns_each_project_with_a_role` / `test_get_hides_a_project_from_a_non_member_as_404` |
| 非メンバーの取得は 403 または 404 | ✅ | 同上＋`tests/api/test_error_statuses.py::test_404_for_a_project_you_are_not_a_member_of` |
| 取得時に自分のロールが分かる | ✅ | `tests/modules/projects/test_project_service.py::test_get_returns_the_members_own_role` |

## F5. 認可の API 層強制

| 条件 | 判定 | 根拠 |
|---|---|---|
| 権限マトリクスに反する操作は Service で拒否される | ✅ | `tests/core/test_authorization.py` 一式＋各 Service のテスト |
| 認可判定は Controller ではなく Service に置かれる | 🔶 | `.importlinter` の契約と構造で担保。**「router に認可判定が無い」ことを検証するテストは無い** |
| HTTP 以外（MCP / ジョブ）から呼んでも同一の認可が通る | 🔶 | Service が `Actor` を引数で受け取る形なので構造的には満たす。`app/cli.py` が Service 経由であることも該当するが、**CLI 経路で認可が働くテストは無い**（`tests/test_cli.py` はパスワード入力の検証のみ） |
| 認可拒否は 403、認証切れは 401 と区別される | ✅ | `tests/api/test_error_statuses.py` の 401 / 403 各テスト |
| 他企画の content_id 指定などの横断アクセスが拒否される | ✅ | `tests/modules/contents/test_content_service.py::test_content_of_another_project_is_404_even_for_a_member_of_both`、`tests/modules/contents/test_content_transition.py::test_content_of_another_project_is_404` |
| 判定単位が企画＋コンテンツの両方で機能する | ✅ | 上の2件＋`test_non_member_gets_404_not_403` |

## F6. コンテンツの CRUD

| 条件 | 判定 | 根拠 |
|---|---|---|
| owner / editor が作成できる（title 必須、初期 status は inbox） | ✅ | `tests/modules/contents/test_content_service.py::test_editor_creates_content_in_inbox_at_version_1`（title 必須は `schemas.ContentCreateRequest` の `min_length=1`。**空 title が 422 になるテストは無い** 🔶） |
| コンテンツは必ずいずれかの企画に属する | 🔶 | `contents.project_id` が NOT NULL + FK。**制約違反を確かめるテストは無い**（API 経路上、企画を経由しないと作れない） |
| メンバーは一覧・取得できる | ✅ | `tests/modules/contents/test_content_service.py::test_reviewer_and_demo_can_read` / `test_list_filters_by_a_single_status` |
| owner / editor は title / body_md を更新できる | ✅ | `test_update_bumps_version_and_keeps_omitted_fields` |
| reviewer / demo の作成・更新・削除は 403 | ✅ | `test_reviewer_and_demo_cannot_write`、`tests/api/test_error_statuses.py::test_403_when_a_reviewer_writes` |
| owner / editor は削除できる（論理削除） | ✅ | `test_deleted_content_disappears_from_list_and_get` |
| version を持ち、更新のたびに増える | ✅ | `test_update_bumps_version_and_keeps_omitted_fields`、`test_allowed_transition_bumps_version_and_appends_one_log_row` |
| 古い version の更新は 409 | ✅ | `test_stale_expected_version_is_409_and_changes_nothing`、`test_conflict_detected_at_flush_is_409`、`tests/api/test_error_statuses.py::test_409_when_expected_version_is_stale` |

## F7. コンテンツの状態遷移

| 条件 | 判定 | 根拠 |
|---|---|---|
| status は6値をとる | ✅ | `tests/modules/contents/test_content_transition.py::test_allowed_matches_the_confirmed_table`（`set(ALLOWED) == set(ContentStatus)`）＋ CHECK 制約 |
| 遷移は専用 API で、title / body_md の更新と分離 | ✅ | `tests/api/test_openapi.py::test_openapi_lists_every_endpoint`（`/transition` が別operation） |
| 定義されていない遷移は 422 | ✅ | `test_disallowed_transition_is_422_and_changes_nothing`（全組み合わせを網羅）、`test_inbox_to_published_is_422`、`tests/api/test_error_statuses.py::test_422_for_a_transition_the_table_forbids` |
| 許可される遷移が design の表どおり | ✅ | `test_allowed_matches_the_confirmed_table` |
| 遷移の権限は owner / editor のみ | ✅ | `test_reviewer_and_demo_cannot_transition` |
| 誰が・いつ・どこからどこへ、が記録される | ✅ | `test_allowed_transition_bumps_version_and_appends_one_log_row`（`from_status` / `to_status` / `actor_user_id` を検証。`created_at` は server_default） |
| 同時実行で不正な状態にならない | ✅ | `test_second_of_two_concurrent_transitions_is_409`、`test_conflict_detected_at_flush_is_409_without_log_row` |

## F8. レイヤー構成と依存契約

| 条件 | 判定 | 根拠 |
|---|---|---|
| `structure.md` のディレクトリ構造に沿う | ✅ | 実ファイル構成（`modules/{domain}/{router,service,repository,models,schemas,deps}.py`） |
| `.importlinter` に一方向の契約がある | ✅ | `backend/.importlinter`（4契約） |
| `lint-imports` が CI で実行され、違反で落ちる | ✅ | `.github/workflows/ci.yml` の import-linter ステップ |
| Service に `Request` / `Response` が import されていない | ✅ | `.importlinter` の契約（`app.modules.*.service` は `fastapi` を禁止） |
| DI は `Depends` に寄せられている | ✅ | `modules/{domain}/deps.py` と router の `Annotated[..., Depends(...)]` |

## F9. テストと API 仕様

| 条件 | 判定 | 根拠 |
|---|---|---|
| Service 層のユニットテストがある | ✅ | `tests/modules/**`（計70件超） |
| **Repository 層のユニットテストがある（企画スコープでの絞り込み）** | ❌ | **無い。** 企画スコープと論理削除の除外は、fake か API 結合テスト経由でしか確かめていない。`design.md` §13 が独立したユニットテストとして挙げている分が抜けている |
| API の結合テストがある（主経路と 401 / 403 / 409 / 422） | ✅ | `tests/api/test_main_path.py`、`tests/api/test_error_statuses.py` |
| OpenAPI が自動生成され参照できる | ✅ | `tests/test_health.py::test_openapi_is_generated`、`tests/api/test_openapi.py` |
| `ruff` / `mypy` / `lint-imports` が CI で緑 | ✅ | `.github/workflows/ci.yml` |

---

## まとめ

| 判定 | 件数 |
|---|---|
| ✅ 対応テストあり | 53 |
| 🔶 実装では満たすがテストが無い | 9 |
| ❌ 満たしていない | 1 |

### 埋めるべき穴（優先度順）

1. **Repository 層のユニットテスト**（F9・❌）。`ContentRepository.get` / `list` が実 DB で企画スコープと `deleted_at` を効かせていることを直接確かめる。いまは fake が同じ振る舞いを真似ているだけなので、**本物の SQL が間違っていてもユニットテストは緑**になる
2. **demo による招待発行が 403**（F3）。`VIEW_ONLY` の積集合で弾かれる経路の確認
3. **CLI 経路で認可が働くこと**（F5）。`add-member` が Service を通ることの確認
4. **空 title が 422**（F6）。スキーマのバリデーションが効いていること
5. 残りの 🔶（router に認可判定が無いこと、`project_id` の NOT NULL 制約）は、テストを足すより**レビューと契約で見るほうが素直**。ここはテストにしない判断もあり得る
