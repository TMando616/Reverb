# tasks.md — foundation（認証・認可・コンテンツ土台）

> **前提**：`requirements.md` / `design.md` は承認済み。
> **環境構築（M0 の 20h 分）は先行実施済み**（commit `8ba5ad3`〜`d9384e0`）。残りの M0 見積りは約 38h。
> **進め方**：モジュール単位で Service / Repository のユニットテストを併走させる（`design.md` §13）。
> **1サブタスク完了ごとにコミット**し、ユーザーにプッシュを促す。
> スコープ外（後続スペック送り）は `requirements.md` §2-2 を参照。

## 0. 環境構築（先行実施済み・参考）

- [x] `backend/` uv プロジェクト・FastAPI 骨格・core スタブ・3モジュール雛形
- [x] `.importlinter` 4契約（`design.md` §11）・`docker-compose.yml`・`.github/workflows/ci.yml`
- [x] `ruff` / `mypy(strict)` / `lint-imports` / `pytest` がローカル・CI で緑

---

## 1. core 層の確定（全機能の前提 / F8）

既存スキャフォールドのスタブを `design.md` §4〜6 の仕様に置き換える。

- [x] 1.1 `core/config.py` の設定項目を確定（`DATABASE_URL` / `SECRET_KEY` / 本番判定フラグ）
- [x] 1.2 `core/db.py`：`get_session` を `design.md` §4-4 に合わせる（`yield` 後に `commit()`、例外時 `rollback()`）。`expire_on_commit=False`
- [x] 1.3 `core/security.py`：Argon2id（`argon2-cffi` を依存に追加）で `hash_password` / `verify_password`。存在しない email 用のダミーハッシュ定数（§4-2）
- [x] 1.4 `core/exceptions.py`：`design.md` §6-3 の体系へ置換（`AuthenticationError`=401 / `ForbiddenError`=403 / `NotFoundError`=404 / `VersionConflictError`=409 / `InvalidStateTransitionError`=422）
- [x] 1.5 `core/exception_handlers.py`：`{ "error": { "code", "message" } }` 封筒に統一。`RequestValidationError` にも独自ハンドラ。commit 失敗（500）はログに残す
- [x] 1.6 `core/authorization.py`：`Actor` 値オブジェクト、`Permission` StrEnum、`ROLE_PERMISSIONS` / `VIEW_ONLY`、`MemberRoleReader` Protocol、`ProjectAuthorizer.require`、`require_not_demo`
- [x] 1.7 ユニットテスト：`ProjectAuthorizer`（role なし→404 / 権限なし→403 / demo は `VIEW_ONLY` 積集合）、`require_not_demo`
- [x] 1.8 `ruff` / `mypy` / `lint-imports` 緑を確認（`core` が `modules` を import しないこと）

## 2. auth モジュール — ログインとセッション（F1）

- [x] 2.1 `auth/models.py`：`users`（`email` UK / `password_hash` / `display_name` / `is_demo`）、`sessions`（`token_hash` UK / `expires_at` / `revoked_at`）
- [ ] 2.2 Alembic 初回マイグレーション生成 → 目視 → `upgrade head`
- [x] 2.3 `auth/repository.py`：`UserRepository`（email 検索・作成）、`SessionRepository`（作成 / `find_valid_with_user` は `users` を `selectinload` で join / revoke）
- [x] 2.4 `auth/service.py`：`AuthService.login`（user が無くてもダミーハッシュ検証してから 401・§4-2 / トークン発行 / `sha256` を `sessions` に保存 / 期限 14日）、`logout`（`revoked_at` を打つ）
- [x] 2.5 `auth/deps.py`：`get_current_actor`（`Header(default=None)` で受け欠落は 401・§4-3 / Bearer パース / `sha256` 照合 / `Actor` を返す）
- [x] 2.6 `auth/schemas.py` + `auth/router.py`：`POST /auth/login` / `POST /auth/logout` / `GET /auth/me`。`main.py` に登録
- [x] 2.7 ユニットテスト：誤資格情報→401 / 有効トークンで保護 API 通過 / 失効・期限切れ→401 / 存在しない email でもダミーハッシュ検証が呼ばれる（列挙対策）

## 3. projects モジュール — 企画・メンバー・認可（F4 / F5 / F2 / F3）

- [ ] 3.1 `projects/models.py`：`projects`（`created_by`）、`project_members`（`role` 文字列 + `UNIQUE(project_id,user_id)` + CHECK）、`invitations`（`token_hash` UK / `email` nullable / `role` / `expires_at` / `accepted_at` / `accepted_user_id`）
- [ ] 3.2 マイグレーション生成 → 目視 → `upgrade head`。インデックス（`project_members(user_id)` / `invitations(token_hash)`）
- [ ] 3.3 `projects/repository.py`：`ProjectRepository`（作成 / 自分がメンバーの企画一覧 / id 取得）、`ProjectMemberRepository`（`role_of` = `MemberRoleReader` を構造的に満たす / メンバー一覧 / owner 行を `SELECT ... FOR UPDATE` で数える / 追加は `ON CONFLICT DO NOTHING` / role 更新 / 削除）
- [ ] 3.4 `ProjectService`：`create`（`require_not_demo` → `projects` + `project_members`(owner) を1トランザクション / flush）、`list_mine`、`get`（`authz.require(PROJECT_VIEW)` → 非メンバーは 404 / 自分の role 付き）
- [ ] 3.5 `MemberService`：`invite`（`PROJECT_MANAGE_MEMBERS` / token 生成 / `sha256` 保存 / 受諾 URL を返す / 期限 7日）、`list_members`、`change_role`（最後の owner 降格ガード・§9-3）、`remove`（最後の owner 除名ガード）
- [ ] 3.6 `InvitationService.accept`：`token_hash` で引く → 無効 / 期限切れ / 受諾済みは一律 404（§6-3）／未ログイン未登録は `display_name`+`password` で `users` 作成／既ログイン demo は 403（§5-3）／`project_members` へ `DO NOTHING`（§9-2）／`accepted_at` 更新。レスポンスは既存 role を返す
- [ ] 3.7 ルーター：`GET/POST /projects`、`GET /projects/{id}`、`POST /projects/{id}/invitations`、`GET /projects/{id}/members`、`PATCH/DELETE /projects/{id}/members/{user_id}`、`POST /invitations/{token}/accept`
- [ ] 3.8 ユニットテスト：非 owner が招待 / ロール変更 / 除名→403 ／非メンバーの企画取得→404 ／最後の owner 降格・除名→403 ／既存メンバーが別ロール招待を受諾しても role 不変（§9-2）／demo が企画作成→403 ／期限切れ招待→404

## 4. CLI bootstrap（§9-0 / F2・F3 の払い出し経路）

- [ ] 4.1 `app/cli.py`：`async with async_session()` を自前で開く土台。`AuthService` / リポジトリ経由で行う（SQL 直書き禁止）
- [ ] 4.2 `create-user --email --display-name [--demo]`（パスワードは対話入力または自動生成して1回だけ標準出力）
- [ ] 4.3 `add-member --project --user --role` / `accept-invitation --token ...`
- [ ] 4.4 `CLAUDE.md`「よく使うコマンド」を実コマンドへ更新

## 5. contents モジュール — CRUD と楽観ロック（F6）

- [ ] 5.1 `contents/models.py`：`contents`（`project_id` / `title` / `body_md` / `status` 文字列 + CHECK / `version` / `deleted_at`）、`__mapper_args__ = {"version_id_col": version}`。`content_status_transitions`（`content_id` / `from_status` / `to_status` / `actor_user_id`）
- [ ] 5.2 マイグレーション生成 → 目視 → `upgrade head`。`contents(project_id, status)` インデックス
- [ ] 5.3 `contents/repository.py`：`ContentRepository`（`get(content_id, project_id)` で必ず project スコープ / `list(project_id, status?)` / 既定で `deleted_at IS NULL`）、`ContentTransitionRepository`（追記のみ）
- [ ] 5.4 `ContentService`：`create`（`CONTENT_WRITE` / 初期 status=`inbox` / flush）、`get`、`list`、`update`（`CONTENT_WRITE` / project スコープ取得 / `expected_version` 照合不一致 409 / flush）、`delete`（論理削除 / flush）
- [ ] 5.5 二段楽観ロック：明示 version 照合 ＋ flush 時 `StaleDataError` を捕捉して 409（§3-3）
- [ ] 5.6 ルーター：`GET/POST /projects/{id}/contents`、`GET/PATCH/DELETE /projects/{id}/contents/{cid}`。`PATCH` は `expected_version` 必須
- [ ] 5.7 ユニットテスト：reviewer / demo の作成・更新・削除→403 ／他企画の `cid` 指定→404（Repository スコープ）／古い version→409 ／論理削除済みは一覧に出ない ／同一内容 PATCH で version 据え置きでも競合検出は壊れない（§3-3）

## 6. コンテンツの状態遷移（F7）

- [ ] 6.1 `ALLOWED` 集合を `contents` モジュール定数として実装（`design.md` §8-1 の確定表）。`in_review → published` は含めない
- [ ] 6.2 `ContentService.transition(actor, project_id, content_id, to, expected_version)`：認可 `CONTENT_TRANSITION` → 取得(404) → version 照合(409) → `to not in ALLOWED[status]` → 422 → status 更新 + flush（version +1）→ `content_status_transitions` に1行
- [ ] 6.3 ルーター：`POST /projects/{id}/contents/{cid}/transition`（`to` / `expected_version`）
- [ ] 6.4 ユニットテスト：`inbox→published` は 422 ／許可された遷移は成功し version +1 と遷移ログ1行 ／reviewer・demo→403 ／同時二重遷移の一方が 409

## 7. 結合テストと API 仕様の仕上げ（F9）

- [ ] 7.1 テスト基盤：外側トランザクション + `join_transaction_mode="create_savepoint"` の `db_session` フィクスチャ（§13-1）。`dependency_overrides[get_session]`
- [ ] 7.2 認証済みクライアントのフィクスチャ（`POST /auth/login` を1回叩く。`users` はフィクスチャで直接作成）
- [ ] 7.3 主経路の結合テスト：ログイン → 企画作成 → コンテンツ登録 → `inbox→adopted→drafting`
- [ ] 7.4 エラー系統の結合テスト：401 / 403 / 404 / 409 / 422 を各1本以上
- [ ] 7.5 `/openapi.json` が参照でき、全エンドポイントが載っていることを確認
- [ ] 7.6 CI（既存 `ci.yml`）で `ruff` / `ruff format` / `mypy` / `lint-imports` / `pytest` すべて緑

## 8. フロントエンド — BFF と最小画面（`design.md` §12 / M0 判定の総仕上げ）

- [ ] 8.1 **【要決定】** `frontend.md` §7 の未決を確定（スタイリング：Tailwind / CSS Modules、データフェッチ層の採否）。必要なら ADR を1本
- [ ] 8.2 `frontend/` を Next.js 16 で作成。作法は `frontend/node_modules/next/dist/docs/` を見て確定（記憶で書かない）
- [ ] 8.3 BFF ルート（`app/api/`）：`auth/login`（token を httpOnly Cookie へ / `Secure` は本番のみ / `maxAge` は `expires_at` から算出）、`auth/logout`、`auth/session`、`projects/**` と `invitations/**` のパススルー（業務判断なし）
- [ ] 8.4 画面：`/login`、`/invite/[token]`、`/projects`（Server Component で一覧＋作成）、`/projects/[id]`（status 別リスト＋作成＋行の遷移操作）
- [ ] 8.5 `docker-compose.yml` に frontend サービスを追加。CI に frontend の lint / build を追加
- [ ] 8.6 手動確認：ブラウザで「ログイン → 企画作成 → ネタ登録 → 状態遷移」が通る（**M0 判定**）

---

## 完了の定義

- `requirements.md` §5 の受け入れ条件 F1〜F9 のチェックボックスをすべて満たす
- `/code-review` を実施し、`requirements.md` との整合を確認する（`CLAUDE.md`「実装検証」）
