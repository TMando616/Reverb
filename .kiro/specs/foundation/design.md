# design.md — foundation（認証・認可・コンテンツ土台）

> **前提**：`requirements.md`（承認済み）、ADR-0002（SQLAlchemy 2.0）、ADR-0009（レイヤー構成）、ADR-0012（FastAPI）、ADR-0014（認証トークンと BFF）。
> **このドキュメントの範囲**：M0 の実装に入る前の設計。`requirements.md` §8 の未決事項をここで解消する。

---

## 1. 設計の狙い

1. **入口が3つ（ブラウザ / MCP / ジョブ）でも認可を1回しか実装しない** — 認可判定を Service 層に置き、HTTP に依存させない
2. **層の分離を CI で強制する** — `.importlinter` の契約を最初のモジュールと同時に入れる
3. **後続スペックが乗る骨格を最小で用意する** — テーブル・例外体系・セッション配線・テスト基盤。機能は足さない

---

## 2. アーキテクチャ全体

### 2-1. バックエンドのモジュール構成

```
backend/app/
├── main.py                  アプリ生成・ルーター登録・例外ハンドラ登録
├── core/
│   ├── config.py            設定（Pydantic Settings）
│   ├── db.py                async engine / async_sessionmaker
│   ├── security.py          パスワードハッシュ・トークン生成/照合
│   ├── authorization.py     Permission 定義・ProjectAuthorizer
│   ├── exceptions.py        アプリ例外の基底と種類
│   └── exception_handlers.py 例外 → HTTP ステータスの対応
├── modules/
│   ├── auth/                ログイン・ログアウト・現在のユーザー解決
│   │   ├── router.py  service.py  repository.py  models.py  schemas.py  deps.py
│   ├── projects/            企画・メンバー・招待
│   └── contents/            コンテンツ CRUD・状態遷移
└── migrations/              Alembic
```

### 2-2. 依存方向（ADR-0009）

```
router.py  ──→  service.py  ──→  repository.py  ──→  DB
（HTTP のみ）    （業務ルール・認可）   （SQLAlchemy）
```

- **`sqlalchemy` を import してよいのは `repository.py` / `models.py` / `core/db.py` / `migrations/` のみ**
- `service.py` は `AsyncSession` を受け取らない。Repository を注入される
- `service.py` に FastAPI（`Request` / `Response` / `Depends`）を import しない
- 認可は `service.py` の中で `ProjectAuthorizer` を呼ぶ。`router.py` では認可しない

### 2-3. DI の組み立て（`deps.py`）

```python
# modules/contents/deps.py
async def get_content_service(
    session: AsyncSession = Depends(get_session),
) -> ContentService:
    return ContentService(
        contents=ContentRepository(session),
        authz=ProjectAuthorizer(ProjectMemberRepository(session)),
        transitions=ContentTransitionRepository(session),
    )
```

Router は `ContentService` だけを `Depends` で受け取り、組み立てを知らない。

---

## 3. データモデル

### 3-1. ER 図（このスペックの範囲）

```mermaid
erDiagram
    users ||--o{ sessions : has
    users ||--o{ project_members : "belongs to"
    projects ||--o{ project_members : has
    projects ||--o{ invitations : has
    projects ||--o{ contents : contains
    users ||--o{ contents : "created"
    contents ||--o{ content_status_transitions : logs

    users {
        int id PK
        string email UK
        string password_hash
        string display_name
        bool is_demo
        timestamptz created_at
        timestamptz updated_at
    }
    sessions {
        int id PK
        int user_id FK
        string token_hash UK
        timestamptz expires_at
        timestamptz revoked_at "nullable"
        timestamptz created_at
    }
    projects {
        int id PK
        string name
        int created_by FK
        timestamptz created_at
        timestamptz updated_at
    }
    project_members {
        int id PK
        int project_id FK
        int user_id FK
        string role "owner | editor | reviewer"
        timestamptz created_at
    }
    invitations {
        int id PK
        int project_id FK
        string email "nullable"
        string role
        string token_hash UK
        timestamptz expires_at
        timestamptz accepted_at "nullable"
        int accepted_user_id FK "nullable"
        int created_by FK
        timestamptz created_at
    }
    contents {
        int id PK
        int project_id FK
        string title
        text body_md
        string status "inbox | adopted | drafting | in_review | published | shelved"
        int version
        int created_by FK
        timestamptz created_at
        timestamptz updated_at
        timestamptz deleted_at "nullable"
    }
    content_status_transitions {
        int id PK
        int content_id FK
        string from_status
        string to_status
        int actor_user_id FK
        timestamptz created_at
    }
```

### 3-2. 補足

| 項目 | 決定 | 理由 |
|---|---|---|
| status の値 | コード上は英語（`inbox` / `adopted` / `drafting` / `in_review` / `published` / `shelved`）。UI 表示の日本語ラベルはフロント側で対応づけ | CLAUDE.md「識別子は英語」 |
| `contents` の削除 | **論理削除**（`deleted_at`）。Repository は既定で `deleted_at IS NULL` で絞る | 後続スペックでリビジョン・公開物が参照する。監査を残す |
| `role` の表現 | 文字列カラム ＋ アプリ側 `Role` StrEnum。DB の ENUM 型は使わない | 値の増減で migration を打たずに済む。CHECK 制約で担保 |
| `project_members` | `UNIQUE (project_id, user_id)` | F2「重複メンバーシップは作られない」 |
| `content_status_transitions` | 遷移専用の追記ログ。`content_revisions` には相乗りしない | 本文の履歴（`content-pipeline`）と状態遷移は変更理由が別。テーブルを分ける |
| インデックス | `contents (project_id, status)`、`sessions (token_hash)`、`project_members (user_id)`、`invitations (token_hash)` | 一覧・認証・メンバー解決の主経路 |

### 3-3. 楽観ロック（ADR-0002 §理由5）

`contents` に `__mapper_args__ = {"version_id_col": version}` を設定する。

- 通常の更新：Service は `expected_version` を受け取り、読み込んだ `content.version` と比較。不一致なら `VersionConflictError`（→ 409）
- flush 時：SQLAlchemy が `UPDATE ... WHERE id=? AND version=?` を発行し `version` を +1。競合で 0 行なら `StaleDataError` を捕捉して同じく 409
- **二段構え**にする理由：明示チェックは「送信前に既に古い」を早期に・分かりやすいエラーで返すため。flush 側のチェックは「読み込み〜flush の間に他トランザクションが更新した」競合を取りこぼさないため

---

## 4. 認証設計

### 4-1. トークン方式（`requirements.md` §8）

**不透明トークン ＋ サーバー側 `sessions` テーブル**を採用する。JWT は採らない。

| 観点 | 判断 |
|---|---|
| F1「ログアウトすると以後 401」 | DB のレコードに `revoked_at` を打てば即失効。JWT だと失効リストが別途必要 |
| ストア | **PostgreSQL**。M0 時点で Redis は無い（ADR-0013 のジョブ基盤で初めて入る） |
| トークン生成 | `secrets.token_urlsafe(32)`。クライアントには生の文字列を返す |
| DB 保存 | `sha256(token)` のみ保存。DB が漏れてもトークンを復元できない |
| 有効期限 | 発行から 14 日（`expires_at`）。スライド更新は M0 ではやらない |
| 照合 | リクエストの Bearer トークンを sha256 して `sessions.token_hash` を引き、`revoked_at IS NULL AND expires_at > now()` を確認 |

### 4-2. パスワード

`core/security.py` に **Argon2id**（`argon2-cffi`）で `hash_password` / `verify_password` を実装する。bcrypt でも要件は満たすが、新規プロジェクトのため現行の推奨に合わせる。

### 4-3. 現在のユーザー解決（`modules/auth/deps.py`）

```python
async def get_current_actor(
    authorization: str = Header(...),
    session: AsyncSession = Depends(get_session),
) -> Actor:
    token = _parse_bearer(authorization)                  # 形式不正 → 401
    row = await SessionRepository(session).find_valid(sha256(token))
    if row is None:
        raise AuthenticationError()                       # → 401
    user = await UserRepository(session).get(row.user_id)
    return Actor(user_id=user.id, is_demo=user.is_demo)
```

`Actor` は `{ user_id: int, is_demo: bool }` の値オブジェクト。**Service にはこの `Actor` だけを渡す**（`Request` も ORM の `User` も渡さない）。

### 4-4. セッション（Unit of Work）のライフサイクルと commit 境界（`requirements.md` §8）

```python
# core/db.py
engine = create_async_engine(settings.database_url)        # postgresql+asyncpg://
async_session = async_sessionmaker(engine, expire_on_commit=False)

# 共通 dependency
async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session() as session:
        try:
            yield session
            await session.commit()      # ハンドラが正常終了したらコミット
        except Exception:
            await session.rollback()
            raise
```

- **1 HTTP リクエスト ＝ 1 セッション ＝ 1 トランザクション**。Service / Repository は `flush()` までしか呼ばない。`commit()` はこの dependency だけ
- ジョブ・MCP（後続スペック）は `async with async_session() as s:` を自前で開く。この dependency は使わない
- ADR-0002 §影響のとおり、詰め替え方針は §7 で定める

---

## 5. 認可設計

### 5-1. Permission と Role（`core/authorization.py`）

```python
class Permission(StrEnum):
    PROJECT_VIEW            = "project:view"
    PROJECT_MANAGE_MEMBERS  = "project:manage_members"
    CONTENT_VIEW           = "content:view"
    CONTENT_WRITE          = "content:write"       # 作成・更新・削除
    CONTENT_TRANSITION     = "content:transition"  # 状態遷移

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER:    frozenset(Permission),                               # 全部
    Role.EDITOR:   frozenset({PROJECT_VIEW, CONTENT_VIEW, CONTENT_WRITE, CONTENT_TRANSITION}),
    Role.REVIEWER: frozenset({PROJECT_VIEW, CONTENT_VIEW}),
}
VIEW_ONLY = frozenset({Permission.PROJECT_VIEW, Permission.CONTENT_VIEW})
```

`requirements.md` §4 の権限マトリクスと一致する。レビューコメント（`collaboration`）・公開（`publishing`）の Permission は各スペックで足す。

### 5-2. ProjectAuthorizer

```python
class ProjectAuthorizer:
    def __init__(self, members: ProjectMemberRepository):
        self._members = members

    async def require(self, actor: Actor, project_id: int, perm: Permission) -> Role:
        role = await self._members.role_of(actor.user_id, project_id)
        if role is None:
            raise NotFoundError("project")          # 非メンバーには存在を隠す（404）
        allowed = ROLE_PERMISSIONS[role]
        if actor.is_demo:
            allowed = allowed & VIEW_ONLY           # demo は role に関わらず閲覧のみ
        if perm not in allowed:
            raise ForbiddenError(perm)              # → 403
        return role
```

| 判断 | 内容 |
|---|---|
| 非メンバーへの応答 | **404**（`NotFoundError`）。「その企画があるか」自体を隠す。F4 の「403 または存在を隠す 404」を 404 側で確定 |
| demo の扱い | `is_demo` なら許可集合を `VIEW_ONLY` と積集合。F3「ロールに関わらず 403」を満たす |
| 認可の位置 | **Service のメソッド冒頭で `await self._authz.require(...)` を明示的に呼ぶ**（`Depends` のガードにしない）。F5「HTTP 以外から呼んでも同一ロジック」を満たすため（`requirements.md` §8 を明示チェック側で確定） |
| 横断アクセス防止 | Repository の取得系は常に `project_id` を引数に取り `WHERE project_id = ?` を付ける。`content_id` だけで引ける経路を作らない（F5） |

### 5-3. Service での使い方（例）

```python
class ContentService:
    async def update(self, actor: Actor, project_id: int, content_id: int,
                     expected_version: int, *, title: str, body_md: str) -> Content:
        await self._authz.require(actor, project_id, Permission.CONTENT_WRITE)
        content = await self._contents.get(content_id, project_id)   # project スコープ
        if content is None:
            raise NotFoundError("content")
        if content.version != expected_version:
            raise VersionConflictError()
        content.title, content.body_md = title, body_md
        await self._contents.flush()
        return content
```

---

## 6. API 設計

### 6-1. エンドポイント一覧

| メソッド | パス | 認証 | 権限 | 説明 |
|---|---|---|---|---|
| POST | `/auth/login` | 不要 | — | email + password → トークン |
| POST | `/auth/logout` | 要 | — | 現在のトークンを失効 |
| GET  | `/auth/me` | 要 | — | 現在のユーザー情報 |
| POST | `/invitations/{token}/accept` | 不要※ | — | 招待受諾（未登録ならパスワード設定） |
| GET  | `/projects` | 要 | 自分がメンバーの企画のみ | 企画一覧（自分の role 付き） |
| POST | `/projects` | 要 | 認証済みなら誰でも（作成者が owner） | 企画作成 |
| GET  | `/projects/{id}` | 要 | PROJECT_VIEW | 企画詳細 |
| POST | `/projects/{id}/invitations` | 要 | PROJECT_MANAGE_MEMBERS | 招待発行（リンク） |
| GET  | `/projects/{id}/members` | 要 | PROJECT_VIEW | メンバー一覧 |
| PATCH | `/projects/{id}/members/{user_id}` | 要 | PROJECT_MANAGE_MEMBERS | ロール変更 |
| DELETE | `/projects/{id}/members/{user_id}` | 要 | PROJECT_MANAGE_MEMBERS | 除名 |
| GET  | `/projects/{id}/contents` | 要 | CONTENT_VIEW | コンテンツ一覧（status で絞り込み可） |
| POST | `/projects/{id}/contents` | 要 | CONTENT_WRITE | 作成（初期 status = `inbox`） |
| GET  | `/projects/{id}/contents/{cid}` | 要 | CONTENT_VIEW | 詳細 |
| PATCH | `/projects/{id}/contents/{cid}` | 要 | CONTENT_WRITE | title / body_md 更新（`expected_version` 必須） |
| DELETE | `/projects/{id}/contents/{cid}` | 要 | CONTENT_WRITE | 論理削除 |
| POST | `/projects/{id}/contents/{cid}/transition` | 要 | CONTENT_TRANSITION | 状態遷移（`to` と `expected_version`） |

※ 招待受諾は未ログインでも叩けるが、トークン（URL の `{token}`）自体が認可の代わり。

- **自己登録エンドポイントは存在しない**（F2）。ユーザーが増える経路は「招待受諾」だけ
- パスの `project_id` を常に明示し、リソースは必ず企画の下にぶら下げる（横断アクセス防止・F5）

### 6-2. リクエスト / レスポンス例

```
POST /auth/login
  req:  { "email": "...", "password": "..." }
  res:  { "token": "<opaque>", "expires_at": "2026-09-13T...Z",
          "user": { "id": 1, "display_name": "...", "is_demo": false } }

POST /projects/1/contents/42/transition
  req:  { "to": "in_review", "expected_version": 7 }
  res:  { "id": 42, "status": "in_review", "version": 8 }
```

### 6-3. エラー体系（`core/exceptions.py` → `exception_handlers.py`）

| 例外クラス | HTTP | 使う場面 |
|---|---|---|
| `AuthenticationError` | 401 | トークンが無い / 不正 / 期限切れ / 失効、ログイン失敗 |
| `ForbiddenError` | 403 | 認証は通ったが権限が無い（demo の書き込み含む） |
| `NotFoundError` | 404 | リソース無し、非メンバーからの企画アクセス |
| `VersionConflictError` | 409 | `expected_version` 不一致、`StaleDataError` |
| `InvalidStateTransitionError` | 422 | 定義されていない状態遷移 |
| Pydantic の `RequestValidationError` | 422 | 入力形式エラー（FastAPI 標準） |

すべて `{ "error": { "code": "...", "message": "..." } }` の形に整形して返す。

---

## 7. Repository の返し方（ADR-0002 §影響の宿題）

**M0 の範囲では ORM モデルインスタンスをそのまま Service まで返す。** ただし次の制約を守る。

- Service は ORM モデルの**属性の読み書きだけ**を行い、`session` / クエリ発行系のメソッド（`.awaitable_attrs` での遅延ロード等）には触れない
- Router に返す直前に、Service または Router で Pydantic の**レスポンススキーマ（`schemas.py`）に詰め替える**。ORM モデルを JSON 化して外に出さない
- 遅延ロードによる N+1 を避けるため、一覧系 Repository は必要な関連を `selectinload` で明示的に取る

> dataclass への完全な詰め替え（Repository の戻り値をドメイン型にする）は、関連が増える `content-pipeline` 以降で費用対効果を再評価する。M0 でここに時間をかけない（Completion over Perfection）。

---

## 8. コンテンツの状態遷移

### 8-1. 遷移表（確定 — `requirements.md` F7 の草案を確定）

| from＼to | inbox | adopted | drafting | in_review | published | shelved |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **inbox** | — | ○ | × | × | × | ○ |
| **adopted** | ○ | — | ○ | × | × | ○ |
| **drafting** | × | ○ | — | ○ | × | ○ |
| **in_review** | × | × | ○ | — | ×※ | ○ |
| **published** | × | × | × | × | — | × |
| **shelved** | ○ | × | × | × | × | — |

※ `in_review → published` は `publishing` スペックで解禁する（公開処理と一体で行うため、`transition` API 単体では許可しない）。`published` を from に持つ遷移（公開取消）も同スペック。

### 8-2. 実装方式

```python
ALLOWED: dict[Status, frozenset[Status]] = {
    Status.INBOX:     frozenset({Status.ADOPTED, Status.SHELVED}),
    Status.ADOPTED:   frozenset({Status.INBOX, Status.DRAFTING, Status.SHELVED}),
    Status.DRAFTING:  frozenset({Status.ADOPTED, Status.IN_REVIEW, Status.SHELVED}),
    Status.IN_REVIEW: frozenset({Status.DRAFTING, Status.SHELVED}),
    Status.PUBLISHED: frozenset(),
    Status.SHELVED:   frozenset({Status.INBOX}),
}
```

- 遷移表はモジュール内の定数。`in_review → published` は `publishing` が `ALLOWED[IN_REVIEW]` に追加する（テーブルを書き換えず集合に足す設計）
- `ContentService.transition(actor, project_id, content_id, to, expected_version)`：
  1. `authz.require(CONTENT_TRANSITION)`
  2. `content` 取得（無ければ 404）
  3. `expected_version` 照合（不一致 409）
  4. `to not in ALLOWED[content.status]` → `InvalidStateTransitionError`（422）
  5. `content.status = to`、`flush()`（`version` が +1）
  6. `content_status_transitions` に1行追記（`from` / `to` / `actor_user_id`）
- 手順3と5の楽観ロックで、同時に走った二重遷移の一方が 409 で弾かれる（F7「不正な状態にならない」）

---

## 9. 招待フロー（`requirements.md` §8）

**M0 はリンク方式のみ。** メール送信基盤は持たない（`email` カラムは任意入力として記録するに留める）。

1. owner が `POST /projects/{id}/invitations`（`role`、任意で `email`）→ サーバーが `token = token_urlsafe(32)` を生成、`sha256` を `invitations` に保存、**受諾 URL（`/invite/{token}`）をレスポンスで返す**。owner がそれを本人に手渡す
2. 受諾者が受諾 URL を開く → フロントが `POST /invitations/{token}/accept` を呼ぶ
   - 未ログイン かつ 未登録：リクエストに `display_name` / `password` を含めさせ、`users` を作成
   - 既ログイン：その `Actor` を使う
3. サーバー：`token_hash` で招待を引き、`accepted_at IS NULL AND expires_at > now()` を確認（切れていれば 410/404）→ `project_members` に `UNIQUE (project_id, user_id)` で upsert 的に追加 → `invitations.accepted_at` / `accepted_user_id` を更新
4. `expires_at` は発行から 7 日

「最後の owner を守る」（F2）：`PATCH`（降格）・`DELETE`（除名）の Service で、対象が対象企画の owner かつ他に owner が居ない場合 `ForbiddenError`。

---

## 10. シーケンス

### 10-1. 認証付きリクエスト ＋ 認可

```mermaid
sequenceDiagram
    participant B as ブラウザ
    participant BFF as Next.js BFF
    participant API as FastAPI Router
    participant DEP as get_current_actor
    participant SVC as ContentService
    participant AZ as ProjectAuthorizer
    participant R as Repository

    B->>BFF: PATCH /api/projects/1/contents/42 (Cookie)
    BFF->>API: PATCH /projects/1/contents/42<br/>Authorization: Bearer <token>
    API->>DEP: 依存解決
    DEP->>R: sessions を token_hash で検索
    R-->>DEP: 有効セッション + user
    DEP-->>API: Actor(user_id, is_demo)
    API->>SVC: update(actor, project_id=1, content_id=42, expected_version, ...)
    SVC->>AZ: require(actor, 1, CONTENT_WRITE)
    AZ->>R: role_of(user_id, 1)
    R-->>AZ: editor
    AZ-->>SVC: OK
    SVC->>R: get(42, project_id=1)
    R-->>SVC: content(version=7)
    SVC->>SVC: expected_version 照合 → 一致
    SVC->>R: flush() → UPDATE ... WHERE id=42 AND version=7
    R-->>SVC: version=8
    SVC-->>API: content
    API-->>BFF: 200 {id:42, version:8, ...}
    BFF-->>B: 200
```

### 10-2. ログイン

```mermaid
sequenceDiagram
    participant B as ブラウザ
    participant BFF as Next.js BFF
    participant API as FastAPI
    B->>BFF: POST /api/auth/login {email, password}
    BFF->>API: POST /auth/login
    API->>API: verify_password（Argon2id）
    API->>API: token = token_urlsafe(32)
    API->>API: sessions に sha256(token) を保存
    API-->>BFF: 200 {token, expires_at, user}
    BFF->>BFF: token を httpOnly Cookie に格納
    BFF-->>B: 200 {user}（token は返さない）
```

---

## 11. レイヤー依存の強制（`.importlinter`）

`backend/.importlinter` に以下の契約を置き、CI（`lint-imports`）で検証する。

```ini
[importlinter]
root_package = app

[importlinter:contract:layers]
name = Controller -> Service -> Repository の一方向
type = layers
layers =
    app.modules.(auth|projects|contents).router
    app.modules.(auth|projects|contents).service
    app.modules.(auth|projects|contents).repository
containers = app

[importlinter:contract:service-no-sqlalchemy]
name = Service は sqlalchemy を知らない
type = forbidden
source_modules =
    app.modules.auth.service
    app.modules.projects.service
    app.modules.contents.service
forbidden_modules =
    sqlalchemy
    app.core.db

[importlinter:contract:service-no-fastapi]
name = Service は FastAPI を知らない
type = forbidden
source_modules =
    app.modules.auth.service
    app.modules.projects.service
    app.modules.contents.service
forbidden_modules =
    fastapi
    starlette
```

---

## 12. フロントエンド（BFF と最小画面）

**このスペックでのフロントは「BFF ＋ M0 判定に必要な最小画面」に限る。** 本格的な画面設計は `content-pipeline` 以降（`.kiro/steering/frontend.md`）。

### 12-1. BFF（`app/api/` — ADR-0014）

| ルート | 役割 |
|---|---|
| `POST /api/auth/login` | FastAPI `/auth/login` に中継 → 返ってきた `token` を `reverb_session` Cookie（httpOnly / Secure / SameSite=Lax / path=/）に格納。ボディはユーザー情報のみ返す |
| `POST /api/auth/logout` | Cookie のトークンで FastAPI `/auth/logout` を叩き、Cookie を破棄 |
| `GET /api/auth/session` | Cookie のトークンで `/auth/me` を中継。未ログインなら 401 |
| `/api/projects/**`, `/api/invitations/**` | Cookie → `Authorization: Bearer` に載せ替えて FastAPI へパススルー。**業務判断はしない** |

- BFF は `contents` / `publications` の業務ルールを一切持たない（越境判定＝`frontend.md` §1）
- ブラウザから FastAPI を直接叩かせない。すべて BFF 経由（ADR-0014）

### 12-2. 画面（最小）

| 画面 | 内容 |
|---|---|
| `/login` | email + password フォーム |
| `/invite/[token]` | 招待受諾（未登録時は display_name + password 入力） |
| `/projects` | 企画一覧（Server Component で BFF から取得）＋ 新規作成 |
| `/projects/[id]` | コンテンツ一覧（status 別のリスト表示で可。カンバン UI は `content-pipeline`）＋ 新規作成 ＋ 各行の状態遷移操作 |

状態管理（`frontend.md` §2）：一覧はサーバー状態（フェッチ層のキャッシュ）、フォーム入力はクライアント状態。M0 ではプッシュ由来の状態は無い。

---

## 13. テスト方針（F9）

| 種別 | 対象 | 例 |
|---|---|---|
| ユニット（Service） | 認可分岐・状態遷移の可否・楽観ロック | `reviewer が update → ForbiddenError`／`inbox→published は InvalidStateTransitionError`／`古い version → VersionConflictError`／`demo（role=owner）が書き込み → ForbiddenError` |
| ユニット（Repository） | 企画スコープ・論理削除の除外 | 他企画の `content_id` を指定しても取得できない／`deleted_at` 済みは一覧に出ない |
| 結合（API） | 主経路と各エラー系統 | ログイン → 企画作成 → コンテンツ登録 → `inbox→adopted→drafting` ／ 401・403・404・409・422 が返ること |
| 契約 | レイヤー依存 | `lint-imports` が緑 |

- テスト DB は Docker Compose の Postgres に専用スキーマ（環境構築タスク側で用意）
- 各テストはトランザクションを張ってロールバックで分離
- Service のユニットテストは Repository を fake / 実 DB のどちらでも書けるようにインターフェースを薄く保つ

---

## 14. requirements.md との対応

| 要件 | 対応セクション |
|---|---|
| F1 ログインとセッション | §4（トークン方式・Argon2id・14日・logout で revoke） |
| F2 招待制ユーザー管理 | §6-1（自己登録 API 無し）・§9（招待フロー・最後の owner 保護） |
| F3 デモアカウント | §5-2（`is_demo` × `VIEW_ONLY`） |
| F4 企画とメンバー | §6-1・§5-2（非メンバーは 404） |
| F5 認可の API 層強制 | §2-2・§5（Service で明示チェック・`project_id` 必須・横断防止） |
| F6 コンテンツ CRUD | §3-3・§6-1・§7（論理削除・`expected_version`） |
| F7 状態遷移 | §8（遷移表確定・二段楽観ロック・遷移ログ） |
| F8 レイヤー契約 | §2-2・§11（`.importlinter` 契約3種） |
| F9 テストと API 仕様 | §13・FastAPI の OpenAPI 自動生成 |

## 15. 未決事項の解消状況（`requirements.md` §8）

| 項目 | 解消 |
|---|---|
| トークン方式・ストア | 不透明トークン ＋ `sessions` テーブル（PostgreSQL）。§4-1 |
| 招待の実体 | M0 はリンク方式のみ。メール送信は持たない。§9 |
| コンテンツ削除 | 論理削除（`deleted_at`）。§3-2 |
| 状態遷移表の確定と `published` の扱い | §8-1 で確定。`published` 絡みは `publishing` へ |
| 状態遷移の記録先 | 専用テーブル `content_status_transitions`。§3-2 |
| 認可の表現方法 | Service 冒頭の明示チェック（`Depends` ガードにしない）。§5-2 |
| Repository の返し方 | M0 は ORM モデルを返す（制約付き）。詰め替えは後続で再評価。§7 |
