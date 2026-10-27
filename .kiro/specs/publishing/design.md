# design.md — publishing（チャネル変換・公開）

> **前提**：`requirements.md`（承認済み・`cd2ee16`）、foundation の design.md（認可・楽観ロック・エラー封筒・1リクエスト1トランザクション）、
> content-pipeline の design.md（リビジョン・プレビュー部品・TanStack Query を使う画面の作り）、ADR-0005（チャネルアダプタ）、ADR-0013（ジョブ基盤・検討中）。
> **このドキュメントの範囲**：M1（22h）を詳しく、M3 は境界と持ち方だけ決める。`requirements.md` §8 の未決事項をここで解消する。

---

## 1. 設計の狙い

1. **M1 はジョブ基盤なしで非同期にする** — 変換を「状態つきの DB の行」として持ち、同じプロセスのワーカーが拾う。M2 で ADR-0013 の基盤に載せ替えるとき、**Service と画面を変えずにワーカーだけ差し替えられる**境界にする（§7）
2. **外部 API は Service から見てポート（Protocol）** — Claude API・Qiita API の具体的な実装は `app/llm` / `app/channels` に置き、Service は Protocol だけを知る。`core` の `MemberRoleReader` と同じ形。テストは fake で成功・失敗・タイムアウトを作る（C10）
3. **公開するのは「チャネル原稿」、本文の正は `contents.body_md` のまま** — 変換・公開で本文を書き換えない。原稿は本文とは別の行で、別の楽観ロックを持つ（§9）
4. **外部に二重に出さない** — Qiita への新規投稿はコンテンツ行のロックと部分 UNIQUE で直列化し、同じコンテンツを二度投稿しない（§10-3）
5. **foundation の骨格に足すだけ** — 認可は Permission を1つ足すだけ（§5）、エラーは封筒に code を足すだけ（§12）

---

## 2. モジュール構成

```
backend/app/
├── modules/publishing/          ★新規
│   ├── models.py        ConversionProfile / ConversionJob / ChannelDraft / ChannelAccount / Publication
│   ├── repository.py
│   ├── service.py       ConversionService / DraftService / AccountService / PublicationService
│   ├── ports.py         ポート（Protocol）と入出力の型・失敗の型。Service と具体実装の両方がここを import する
│   ├── schemas.py
│   ├── router.py
│   └── deps.py          ポートに具体実装（Claude・Qiita・暗号化）を差し込む
├── channels/                    ★新規（structure.md に既にある置き場所）
│   ├── capabilities.py  ChannelCode と CAPABILITIES（ADR-0005 の capabilities を Python で）
│   ├── qiita.py         QiitaClient（httpx）
│   └── urls.py          チャネルごとの URL 検証（M3）
├── llm/                         ★新規
│   ├── converter.py     ClaudeConverter（anthropic SDK）
│   └── prompts.py       プロファイル → system プロンプトの組み立て
├── jobs/                        ★新規（structure.md に既にある置き場所）
│   └── worker.py        変換ジョブのワーカー（M1 は lifespan で起動）
└── core/
    └── crypto.py        ★新規 TokenCipher（Fernet）
```

| 判断 | 理由 |
|---|---|
| `modules/contents` に足さず `modules/publishing` を作る | contents はすでに大きい（service.py 362 行）。公開まわりは外部 API・暗号化・ワーカーを伴い、変更の理由が本文の編集と別。content-pipeline §2 の「500 行で割る」に先回りで当たる |
| publishing からコンテンツへの書き込みはポート経由 | `PublicationService` は `ContentGateway`（Protocol）を受け、実体は `ContentService` を deps で渡す。**状態遷移と遷移ログは contents の持ち物のまま**にし、publishing が `contents` のテーブルを直接書かない |
| `llm/` を新設する | structure.md に置き場所が無い。チャネルアダプタ（公開先）と LLM（変換の道具）は別物で、`channels/` に混ぜると「Claude もチャネルの1つ」に見える。**structure.md を実装前に更新する**（tasks.md 0.x） |
| チャネルの定義を DB に置かない | §3-2 |

### `.importlinter` の変更

- `layers` の containers に `app.modules.publishing` を足す
- `service-no-sqlalchemy` / `service-no-fastapi` の source に `app.modules.publishing.service` を足す
- **新しい契約**：`app.modules.publishing.service` は `app.channels.qiita` / `app.llm` / `anthropic` / `httpx` を import しない（ポートだけを知る）。`app.channels.capabilities` は振る舞いを持たない定義なので import してよい（§6 の分岐で使う）
- **新しい契約**：`app.jobs` は `*.repository` を import しない（structure.md「ジョブは Service を呼ぶ」）。組み立ては `deps` の関数を使う

---

## 3. データモデル

### 3-1. ER 図（このスペックで足す部分）

```
users ─────────────────────────────┐
  │                                 │
  └─ channel_accounts               │  ユーザー単位（企画に属さない）
       user_id, channel, encrypted_token, external_user_id
                                    │
projects                            │
  ├─ conversion_profiles            │  企画×チャネルで1件（無ければコードの既定値から作る）
  │    project_id, channel, structure, tone, first_person, banned_phrases[], version
  │                                 │
  └─ contents ──────────────────────┤
       ├─ conversion_jobs           │  変換1回＝1行。キュー兼実行履歴
       │    status, channel, requested_by, source_revision_no, profile_snapshot,
       │    result_title / result_body / result_extra, error_code, error_message, usage
       │
       ├─ channel_drafts            コンテンツ×チャネルで1件。公開するのはこれ
       │    channel, title, body, extra, version, source_revision_no, applied_job_id,
       │    edited_after_apply, pending_job_id
       │
       └─ publications              公開物
            channel, external_id, url, visibility, published_at, published_by,
            last_pushed_at, cancelled_at, cancelled_by
```

### 3-2. 補足

| 項目 | 決定 | 理由 |
|---|---|---|
| **チャネルの定義** | **コードに置く**（`ChannelCode` StrEnum ＋ `CAPABILITIES` dict）。テーブルにはチャネルを `text` ＋ CHECK 制約で持つ | capabilities は振る舞い（Qiita なら API を叩く）と一体で、**チャネルを足すにはどのみちコードが要る**。DB に写しを置くとずれる。requirements-overview §8 の `channels` テーブルは作らない（§17 で overview を直す） |
| 変換プロファイル | **企画×チャネルで1件**。項目ごとの列（`structure` / `tone` / `first_person` / `banned_phrases text[]`）＋ `version` | 権限マトリクスが「企画単位の owner が編集」なので企画に持たせる。列に分けるのは、編集画面（M3）でフォームにしやすく、プロンプトの組み立て（§8-2）で順番を固定できるから |
| プロファイルの初期値 | コード（`llm/prompts.py` の `DEFAULT_PROFILES`）に置き、**初めて変換するときにその企画の行を作る** | 企画を作るたびに4行入れる、を避ける。シードのマイグレーションも要らない |
| 変換ジョブ | **`conversion_jobs` 1行が「キューの1件」と「実行履歴の1行」を兼ねる** | M1 に別のキューは無い（§7）。履歴（C3）を別テーブルにすると同じ情報を2回書く |
| `profile_snapshot` | `jsonb`。変換時のプロファイルの内容を丸ごと写す | C2「後でプロファイルを変えても、過去の変換が何で作られたか分かる」。プロファイルの版の履歴テーブルを持つより単純 |
| `source_revision_no` | 変換したときの**最新リビジョン番号**を記録する。`contents.version` ではない | `version` は状態遷移・`source_note_path` でも進む（content-pipeline §4）。**公開で `公開済` に遷移しただけで「原稿が古い」と出てしまう。** リビジョンは本文（タイトル・本文）が変わったときだけ増えるので、比較に使える |
| チャネル原稿 | **コンテンツ×チャネルで1件**（UNIQUE）。版の履歴は持たない | 原稿は「公開する直前の作業台」。履歴は変換ジョブの結果（`result_*`）に残る。原稿の版管理まで持つと content-pipeline のリビジョンをもう1つ作ることになる |
| `extra` | `jsonb`。Qiita なら `{"tags": ["Python", "FastAPI"]}` | チャネル固有の項目は Qiita のタグくらいで、列にするほど種類が無い。形は Pydantic で検証する |
| Qiita トークン | `channel_accounts`（ユーザー×チャネルで1件）。`encrypted_token bytea` | §10-1 |
| 公開物 | **論理削除（`cancelled_at` / `cancelled_by`）**。取消した行も残る | C8「取消は記録として残る」。`metrics` は `cancelled_at IS NULL` の公開物だけを取りに行けばよく、取消前に溜めた指標も消えない |
| 公開範囲 | `visibility text`（`public` / `private`）。Qiita のみ値を持ち、他は NULL | 限定共有（C6）を記録するため |

### 3-3. 制約とインデックス

| テーブル | 制約・インデックス | 目的 |
|---|---|---|
| `conversion_jobs` | **部分 UNIQUE `(content_id, channel) WHERE status IN ('queued', 'running')`** | 二重実行の禁止（C3）を DB で止める。違反は 409 `conversion_in_progress` |
| `conversion_jobs` | 部分インデックス `(created_at) WHERE status = 'queued'` | ワーカーが待機中を古い順に拾う |
| `conversion_jobs` / `channel_drafts` / `publications` | 複合 FK `(content_id, project_id) → contents(id, project_id)` | 企画をまたぐ参照を DB で止める（content-pipeline §3-3 と同じ） |
| `channel_drafts` | UNIQUE `(content_id, channel)` | 原稿は1件 |
| `publications` | **部分 UNIQUE `(content_id, channel) WHERE cancelled_at IS NULL`** | 同じコンテンツを同じチャネルに二重に公開しない（C6・C7）。Phase 1 は「X で同じネタを2回告知する」を扱わない |
| `publications` | 部分 UNIQUE `(channel, external_id) WHERE cancelled_at IS NULL` | 同じ URL・記事の二重登録（C7） |
| `publications` | インデックス `(project_id, published_at DESC)` | 企画の公開済み一覧（C8） |
| `channel_accounts` | UNIQUE `(user_id, channel)` | 1人1チャネル1トークン |
| `conversion_profiles` | UNIQUE `(project_id, channel)` | 企画×チャネルで1件 |

---

## 4. 状態遷移の変更

foundation の遷移表（`ALLOWED`）には **`published` を遷移先として足さない。** foundation §8-2 のコメントは「publishing が集合に足して解禁する」としていたが、足すと汎用の遷移 API から公開物なしで `公開済` にできてしまう（C8 に反する）。

| 遷移 | 起きる場所 | 条件 |
|---|---|---|
| `drafting` / `in_review` → `published` | **公開操作の中だけ**（`ContentService.mark_published`） | 公開物を作ったのと同じトランザクション |
| `published` → `published` | Qiita の更新、2つ目のチャネルへの公開 | 状態は変えない。遷移ログも書かない |
| `published` → `drafting` | **公開取消で、取り消されていない公開物が0件になったとき**（`ContentService.mark_unpublished`） | 同じトランザクション。遷移ログを書く |
| その他の `published` からの遷移 | 汎用 API では引き続き不可（422） | 公開物が残っているのに `見送り` 等へ動かせると、指標を取り続ける対象と状態が食い違う |

- 公開できる状態は `PUBLISHABLE_FROM = {drafting, in_review, published}`。`受信箱` / `採用` / `見送り` から公開しようとすると 422 `invalid_state_transition`
- `mark_published` / `mark_unpublished` は `ContentService` に足す。publishing からは `ContentGateway` ポート越しに呼ぶ（§2）
- 汎用 API に `to=published` が来たら、これまでどおり遷移表で 422 になる。テストで固定する（C8）

---

## 5. 認可

**Permission を1つ足す：`CONTENT_PUBLISH`（owner のみ）。** `ROLE_PERMISSIONS[OWNER]` は `frozenset(Permission)` なので自動で入り、editor・reviewer には足さない。demo は `VIEW_ONLY` との積集合で落ちる。

| 操作 | Permission |
|---|---|
| チャネル原稿・変換履歴・公開物・プロファイルの閲覧 | `CONTENT_VIEW` |
| 変換の実行、チャネル原稿の編集、再変換結果の採用 | `CONTENT_WRITE` |
| Qiita への投稿・更新、貼り戻し（M3）、公開取消 | **`CONTENT_PUBLISH`** |
| プロファイルの編集（M3・任意） | `PROJECT_MANAGE_MEMBERS` に相乗りせず、**`CONTENT_PUBLISH` を使う**（owner のみ。プロファイルは公開物の体裁を決めるので公開と同じ重さ） |

**ユーザー単位の操作（`AccountService`）は企画の認可を通らない。** 対象は常に `actor.user_id` の行で、他人の行を指定する API を作らない。`actor.is_demo` なら登録・削除は 403（閲覧は自分の「未登録」が見えるだけなので通す）。

公開時に使うトークンは **公開操作をした owner 本人のもの**。企画に owner が複数いても、他人のトークンで投稿しない。

---

## 6. API 一覧

| メソッド | パス | 権限 | 説明 | 時期 |
|---|---|---|---|---|
| GET | `/channels` | ログイン | チャネル一覧と capabilities | M1 |
| GET | `/projects/{id}/contents/{cid}/channels/{ch}` | VIEW | **公開画面の1回分**：原稿・最新の変換ジョブ・公開物・最新リビジョン番号をまとめて返す | M1 |
| POST | `/projects/{id}/contents/{cid}/channels/{ch}/conversions` | WRITE | 変換の実行。**202** と ジョブを返す | M1 |
| GET | `/projects/{id}/contents/{cid}/conversions` | VIEW | 変換の履歴（新しい順・結果の本文なし） | M1 |
| GET | `/projects/{id}/contents/{cid}/conversions/{job_id}` | VIEW | ジョブ1件（状態・結果） | M1 |
| PUT | `/projects/{id}/contents/{cid}/channels/{ch}/draft` | WRITE | 原稿の保存 `{title, body, extra, expected_version}` | M1 |
| POST | `/projects/{id}/contents/{cid}/channels/{ch}/draft/apply` | WRITE | 保留中の変換結果で原稿を置き換える `{job_id, expected_version}` | M1 |
| POST | `/projects/{id}/contents/{cid}/channels/qiita/publish` | PUBLISH | Qiita へ新規投稿 `{visibility, expected_draft_version}` | M1 |
| POST | `/projects/{id}/contents/{cid}/channels/qiita/push` | PUBLISH | 公開済みの Qiita 記事を原稿で更新 `{expected_draft_version, visibility?}` | M1 |
| POST | `/projects/{id}/contents/{cid}/publications` | PUBLISH | 貼り戻し `{channel, url}`（intent / manual） | M3 |
| DELETE | `/projects/{id}/publications/{pub_id}` | PUBLISH | 公開取消（論理削除） | M1 |
| GET | `/projects/{id}/publications` | VIEW | 企画の公開済み一覧（コンテンツ単位にまとめる） | M1 |
| GET | `/me/accounts/qiita` | 本人 | 登録状況 `{registered, external_user_id}`。**トークンは返さない** | M1 |
| PUT | `/me/accounts/qiita` | 本人 | 登録・差し替え `{token}`。Qiita に問い合わせて確認してから保存 | M1 |
| DELETE | `/me/accounts/qiita` | 本人 | 削除 | M1 |

- `{ch}` は `ChannelCode` の値（`qiita` / `x` / `note` / `podcast`）。Path の型で検証し、知らない値は 422
- 公開系のパスに `qiita` を書いているのは、M1 の auto が Qiita だけだから。**分岐は Service で `CAPABILITIES[ch].publish == "auto"` を見る**（C1）。X を auto にする日が来たら `.../channels/{ch}/publish` に一般化する
- 公開画面の取得を1本にまとめるのは、画面がジョブの状態を取り直すとき（§13-3）に1リクエストで済ませるため
- `/me/accounts/...` は企画の外なので `/projects` の下に置かない

---

## 7. 変換ジョブの実行（M1・ジョブ基盤なし）

### 7-1. なぜ FastAPI の BackgroundTasks を使わないか

**このアプリの commit はレスポンス送信後に `get_session` の後片付けで走る**（foundation §4-4）。BackgroundTasks もレスポンス送信後に動くので、**ジョブの行が commit される前にバックグラウンド処理が始まる可能性がある。** 順番を FastAPI の内部の実装に頼ることになり、バージョンで変わったこともある。

さらに、BackgroundTasks はプロセスが落ちると消え、再起動しても拾い直せない。

### 7-2. 決定：DB をキューにした常駐ワーカー

```
POST /conversions                         ワーカー（同じプロセスの asyncio タスク）
  └ ConversionService.request()             ループ（2秒ごと）
      ├ 認可・状態確認                        ├ ① 拾う：別セッションで
      ├ INSERT conversion_jobs(queued)         │   SELECT ... WHERE status='queued'
      │   ※部分 UNIQUE で二重実行は 409        │   ORDER BY created_at LIMIT 1
      └ 202 を返す → commit                    │   FOR UPDATE SKIP LOCKED
                                               │   → running・started_at → commit
                                               ├ ② 変換：DB の外で Claude API を呼ぶ
                                               │   （トランザクションを持ったまま待たない）
                                               └ ③ 書く：別セッションで
                                                   succeeded＋結果／failed＋理由
                                                   → 原稿へ反映（§9-2）→ commit
```

- **`FOR UPDATE SKIP LOCKED`** で、ワーカーが複数動いても（`uvicorn --workers` や将来のコンテナ分割）同じ行を2つが拾わない
- ①と③の間で DB の接続もロックも持たない。変換は数十秒〜数分かかるため
- **commit の持ち主はワーカー**（cli.py と同じく、Service の外にある唯一の commit）。Service は flush だけ
- 起動：`main.py` の lifespan でワーカーのタスクを作り、終了時にキャンセルする。設定 `RUN_CONVERSION_WORKER`（既定 `true`）。テストでは `false`

### 7-3. 止まったジョブの回収

プロセスが ②の途中で落ちると `running` のまま残り、部分 UNIQUE のせいで**そのコンテンツ×チャネルが二度と変換できなくなる。**

- ワーカーはループのたびに、`status = 'running' AND started_at < now() - 15分` の行を `failed`（`error_code = 'interrupted'`）にする
- 15分は Claude 呼び出しのタイムアウト（§8-1 の 10分）より長くとる。生きている実行を回収しない

### 7-4. M2 での載せ替えの境界

| 層 | M1 | M2（ADR-0013 で選んだ基盤） | 変わるか |
|---|---|---|---|
| `ConversionService.request()` | 行を `queued` で INSERT | 同じ ＋ キューに id を積む（`JobDispatcher` ポート） | **ポートの実装だけ** |
| `ConversionService.claim / complete / fail` | ワーカーが呼ぶ | ジョブのプロセッサが呼ぶ | 変わらない |
| `jobs/worker.py` | ポーリングのループ | 基盤のワーカー定義 | **ここだけ書き直す** |
| 画面 | 状態を取り直す | SSE で受ける（M2） | 取り直しは残してよい |

`JobDispatcher` は M1 では何もしない実装（行を INSERT した時点でワーカーが見つける）。**ポートだけ M1 で切っておく。**

この判断は **ADR-0017「M1 の変換ジョブを DB キューで回す」** に残し、ADR-0013 から参照する（tasks.md 0.x）。

---

## 8. Claude API の呼び出し

`/claude-api` スキルを読んで決めた（2026-10-18）。実装の直前にもう一度スキルを読む（CLAUDE.md）。

### 8-1. 呼び出しの形

| 項目 | 決定 | 理由 |
|---|---|---|
| SDK | 公式 `anthropic`（`AsyncAnthropic`）。生の HTTP にしない | スキルの指定。型付きの例外と再試行が付いてくる |
| モデル | **`claude-opus-5-5`**。設定 `CONVERSION_MODEL` で差し替え可 | スキルの既定。文体を写す作業は品質が出るモデルで始め、変えるのは実際のコストを見てから |
| 思考 | `thinking` を送らない（Opus 5.5 は常に adaptive。`disabled` は 400） | スキル |
| effort | **`output_config.effort = "medium"` を明示する**。設定で変えられる | Opus 5.5 の既定は medium だが、暗黙に頼ると既定が変わったときに挙動が変わる |
| 出力の形 | **structured outputs**（`output_config.format` に JSON Schema）。`{title, body, tags}` を受け取り、Pydantic で検証 | 「本文だけ」「前置きが付く」のゆれを無くす。Qiita のタグも同時に出させる（§10-4） |
| ストリーミング | **`messages.stream(...)` ＋ `get_final_message()`** | 記事1本分の出力は長い。スキルは長い出力にストリーミングを推奨（HTTP タイムアウト回避）。途中経過は使わない |
| `max_tokens` | **64000** | スキルのストリーミング時の既定。思考も含めて数えるので低く置かない。打ち切られたら `stop_reason == "max_tokens"` で失敗にする |
| タイムアウト | クライアントの `timeout = 600秒` | §7-3 の回収（15分）より短く |
| 再試行 | SDK の既定（`max_retries = 2`：429・5xx・接続エラー）だけ。**アプリ側で再試行を重ねない** | requirements §6「自動の再試行で何度も呼ばない」。失敗したらユーザーが再実行する |
| refusal | **`fallbacks: "default"`（beta `server-side-fallback-2026-07-01`）を付ける**。それでも `stop_reason == "refusal"` なら失敗（`error_code = 'refused'`） | スキルが Opus 5.5 では既定で付けるよう求めている。記事の変換で拒否はまず起きないが、起きたときに黙って空の原稿を作らない |
| 記録 | `usage`（入力・出力トークン）と `_request_id` をジョブの行に残す。**本文・プロンプトはログに出さない** | コストの把握と障害時の問い合わせ用 |
| API キー | `ANTHROPIC_API_KEY`（環境変数）。設定クラスで受けず、SDK に解決させる | スキルの既定の解決順に任せる。レスポンス・ログに出す経路を作らない |

### 8-2. プロンプトの組み立て（`llm/prompts.py`）

```
system（固定部分。チャネルごとに同じ文字列）
  - 役割：「発信者本人の文体を保ったまま、{チャネル} 向けの原稿に書き直す編集者」
  - 出力の約束：JSON の各フィールドの意味、本文は Markdown（X はプレーンテキスト）
  - してはいけないこと：本文に無い事実・体験を足さない、本人の一人称・口癖を変えない
system（プロファイル部分）
  - 構成ルール（structure）／語尾（tone）／一人称（first_person）／禁則フレーズ（banned_phrases）を見出し付きで並べる
user
  - タイトル
  - 本文（body_md をそのまま。切り詰めない）
  - その企画の既存タグ名の一覧（タグ候補を既存に寄せるため）
```

- **本文は切り詰めない**（スキルの注意）。本文の上限は content-pipeline の `BODY_MD_MAX_LENGTH`（10万文字）で、Opus 5.5 の文脈長（1M トークン）に十分収まる
- プロファイル部分は企画ごとに変わるので、プロンプトキャッシュは狙わない（最小キャッシュ長にも届かない見込み）
- Qiita の既定プロファイルは、グローバル CLAUDE.md §5 の Qiita の節（構成・禁則フレーズ・声の抽出）を移植する。**禁則フレーズは配列にして、プロンプトに箇条書きで入れる**

### 8-3. エラーの対応表

| 起きたこと | `error_code` | 画面の文言の方向 |
|---|---|---|
| `anthropic.RateLimitError`（再試行後も） | `rate_limited` | 少し待ってから再実行 |
| `anthropic.APIStatusError`（5xx） / `APIConnectionError` / `APITimeoutError` | `upstream_unavailable` | 時間をおいて再実行 |
| `anthropic.AuthenticationError` / `PermissionDeniedError` | `misconfigured` | 管理者向けの設定の問題（**キーの値は出さない**） |
| `anthropic.BadRequestError` | `bad_request` | 本文が長すぎる等。`request_id` を出す |
| `stop_reason == "max_tokens"` | `truncated` | 本文が長すぎる |
| `stop_reason == "refusal"` | `refused` | 変換できなかった |
| JSON が Schema に合わない | `invalid_output` | 再実行 |
| §7-3 の回収 | `interrupted` | 再実行 |

例外は**具体的なものから順に**捕まえる（スキルの注意）。`except Exception` で丸めない。

### 8-4. ポート

```python
class Converter(Protocol):
    async def convert(self, request: ConversionInput) -> ConversionOutput: ...
    # 失敗は ConversionFailed(error_code, message, request_id) を投げる
```

`ConversionInput` / `ConversionOutput` は `ports.py` に置く dataclass。`llm/converter.py` がこれを実装し、テストは `FakeConverter`（成功・各失敗・遅延を設定できる）を使う。

---

## 9. チャネル原稿

### 9-1. 保存と楽観ロック

- `channel_drafts.version` を SQLAlchemy の `version_id_col` にする（contents と同じ二段構え：`expected_version` の照合 → flush 時の `WHERE version = ?`）
- **原稿の保存はリビジョンを作らない**（原稿は作業台。履歴は変換ジョブの `result_*`）
- 原稿の保存で `edited_after_apply = true` にする

### 9-2. 変換結果の反映（再変換で手直しを消さない）

ジョブが成功したとき（§7-2 の③）：

| 原稿の状態 | 反映 |
|---|---|
| まだ無い | 結果で原稿を作る |
| ある・`edited_after_apply = false`（変換後に手で直していない） | 結果で置き換える。`version` が進む |
| ある・**`edited_after_apply = true`**（手で直した） | **置き換えない。** `pending_job_id` にジョブを記録するだけ |

- 画面は `pending_job_id` があれば「新しい変換結果があります」と出し、**結果のプレビュー**と［この結果で置き換える］を見せる
- 置き換えは `POST .../draft/apply {job_id, expected_version}`。手で直した原稿を持った画面が古ければ 409
- requirements C4 の2案（確認して上書き／結果を並べる）のうち、**結果を並べる側**を選んだ。変換は非同期なので、実行ボタンを押した時点の確認だけでは、結果が出るまでの間の手直しを守れない

### 9-3. 原稿が古いことの判定

`channel_drafts.source_revision_no < 最新のリビジョン番号` なら「変換後に本文が更新されています」と出す（§3-2 の理由で `contents.version` は使わない）。公開は止めない（警告のみ）。

---

## 10. Qiita

### 10-1. トークンの暗号化（`core/crypto.py`）

| 項目 | 決定 | 理由 |
|---|---|---|
| 方式 | **Fernet（`cryptography`）**。AES-128-CBC ＋ HMAC-SHA256 の認証付き暗号 | 自前で暗号を組まない。改ざんされた暗号文は復号で弾ける |
| 鍵 | 環境変数 **`TOKEN_ENCRYPTION_KEYS`**（カンマ区切り）。`SECRET_KEY` とは別 | DB と鍵を別に管理する（C5）。用途ごとに鍵を分ける |
| 鍵の差し替え | **`MultiFernet`**：先頭の鍵で暗号化し、全部の鍵で復号を試す。古い鍵の暗号文は、次にトークンを使ったときに先頭の鍵で暗号化し直す | 鍵を替えても既存のトークンが読める |
| 本番の設定漏れ | `ENVIRONMENT=production` で鍵が空なら起動時に落とす（`SECRET_KEY` と同じ扱い） | 黙って起動させない |
| 例外・ログ | 復号失敗は `TokenUnavailableError`（メッセージにトークンも暗号文も含めない） | C5 |

`TokenCipher` は `core` に置く（modules を知らない汎用部品）。Service には `TokenCipher` のポートとして渡す。

### 10-2. 登録時の確認

`PUT /me/accounts/qiita` → `GET /api/v2/authenticated_user` を叩き、200 なら `id`（Qiita のユーザー名）を `external_user_id` に入れて保存。401 / 403 なら 422 `invalid_qiita_token`。書き込み権限（`write_qiita`）の有無はこの API では分からないので、**画面で「write_qiita スコープで発行してください」と案内する**。足りなければ最初の投稿が 403 になり、§10-5 の表で同じ案内を出す。

### 10-3. 新規投稿の流れ（二重投稿を作らない）

```
PublicationService.publish_qiita(actor, project_id, content_id, visibility, expected_draft_version)
  1. authz.require(CONTENT_PUBLISH)
  2. コンテンツを SELECT ... FOR UPDATE（ContentGateway.lock_for_publish）
     → 同じコンテンツの公開操作をここで直列化する
  3. 状態が PUBLISHABLE_FROM か（違えば 422）
  4. 取り消されていない Qiita の公開物があれば 409 publication_exists（「更新」を使う）
  5. 原稿の version 照合（409）、Qiita の制約の検証（422 §10-4）
  6. トークンを復号（無ければ 409 qiita_token_missing）
  7. QiitaClient.create_item(...)            ← 外部への送信（ロックを持ったまま。数秒）
  8. publications に INSERT、mark_published（遷移ログ）、flush
  9. 戻る → get_session が commit（ロック解放）
```

- **二重クリック・2タブ**：2つ目のリクエストは 2. で1つ目の commit を待ち、4. で 409 になる。部分 UNIQUE（§3-3）は最後の砦
- **7. が成功して 8. 以降が失敗する**（DB の障害）と、Qiita に記事があるのに記録が無い状態になる。Qiita API に冪等キーは無いので、ここは**起きたら気づける・直せる**ようにする：
  - 7. の直後に、外部 ID と URL を `INFO` で記録する（トークン・本文は出さない）
  - 8. で例外が出たら `ERROR` でもう一度外部 ID を出す
  - 直す手段は **貼り戻し（`POST .../publications`）を Qiita にも開ける**（M3 の機能。Qiita の URL から外部 ID を取り出す）。M1 では起きたら手で直す前提で、手順を README に書く
- ロックを持ったまま外部 API を待つのは、利用者が数人のこのアプリでは問題にならない。待たせる相手は同じコンテンツを同時に公開しようとした人だけ

**更新（push）** は 4. が逆（公開物が無ければ 404）で、7. が `PATCH /api/v2/items/:id`、8. が `last_pushed_at` の更新になる。状態は変えない。

### 10-4. Qiita の制約とタグ

| 項目 | 決定 |
|---|---|
| タグの出どころ | **変換で LLM に出させる**（§8-1 の `tags`）。プロンプトに企画の既存タグを渡して寄せる。原稿の画面で人が直す |
| タグの数 | **1〜5個**（Qiita の画面の制約。API ドキュメントに明記が無いので、実装時に実際に投稿して確かめる） |
| タグの形 | Qiita の `{name, versions: []}` に変換して送る。名前の前後の空白を除き、重複を除く |
| タイトル | 必須・空白のみ不可。長さの上限は実装時に確認する |
| 公開範囲 | `private`（限定共有）を選べる。**限定共有 → 一般公開は更新で変えられる。一般公開 → 限定共有は Qiita が許さない想定で、画面で選ばせない**（実装時に確認） |
| 送らないもの | `tweet`（X への自動投稿）は送らない。告知は M3 の X（intent）で自分で行う |

### 10-5. Qiita API のエラー

| Qiita の応答 | 返すもの |
|---|---|
| 401 | 409 `qiita_token_invalid`（トークンの再登録へ誘導） |
| 403 | 409 `qiita_token_invalid`（`write_qiita` スコープの案内を添える） |
| 400 / 422 | 422 `qiita_rejected`（Qiita の `message` をそのまま添える。トークンは含まない） |
| 404（更新時） | 409 `qiita_item_missing`（Qiita 側で消された。公開取消を案内） |
| 429 | 503 `qiita_rate_limited` |
| 5xx・タイムアウト・接続エラー | 502 `qiita_unavailable` |

`QiitaClient` は `httpx.AsyncClient`（タイムアウト 15秒、再試行なし）。**投稿（POST）は再試行しない**（冪等でないため。二重投稿の原因になる）。

---

## 11. 公開物と公開取消

- 取消は `cancelled_at` / `cancelled_by` を入れるだけ。**Qiita の記事は消さない**（画面に「Qiita 上の記事は残ります」と出す）
- 取消のあと、取り消されていない公開物が0件なら `mark_unpublished`（`published → drafting`）
- 取り消した公開物を元に戻す操作は作らない。必要なら貼り戻し（M3）でもう一度登録する
- 企画の公開済み一覧：取り消されていない公開物を、コンテンツごとにまとめて新しい順に返す（`[{content: {id, title}, publications: [{channel, url, published_at}]}]`）

### 11-1. 貼り戻し（M3）

- `channels/urls.py` にチャネルごとの検証を置く：ホスト名の完全一致（`qiita.com` / `x.com`・`twitter.com` / `note.com` / ポッドキャストは設定したホスト）＋ パスの形。外部 ID は URL から取り出す（X なら status の ID、note なら記事のキー）
- **貼られた URL にサーバーからアクセスしない**（SSRF を作らない。形の検証だけ）
- Qiita も貼り戻しを受ける（§10-3 の復旧用）

---

## 12. エラー体系（追加分）

foundation の封筒（`{ "error": { "code", "message" } }`）をそのまま使う。

| 状況 | HTTP | `error.code` |
|---|---|---|
| 同じコンテンツ×チャネルで変換が待機中・実行中 | 409 | `conversion_in_progress` |
| 原稿が他で更新された | 409 | `version_conflict`（既存） |
| 取り消されていない公開物がある（新規投稿・貼り戻し） | 409 | `publication_exists` |
| Qiita のトークンが無い | 409 | `qiita_token_missing` |
| Qiita のトークンが無効・権限不足 | 409 | `qiita_token_invalid` |
| Qiita 側で記事が消えている（更新） | 409 | `qiita_item_missing` |
| 登録しようとしたトークンが無効 | 422 | `invalid_qiita_token` |
| 原稿が Qiita の制約を満たさない | 422 | `invalid_draft` |
| Qiita が投稿を拒否した | 422 | `qiita_rejected` |
| 公開できない状態から公開しようとした | 422 | `invalid_state_transition`（既存） |
| 貼られた URL の形が合わない（M3） | 422 | `invalid_publication_url` |
| Qiita の障害・タイムアウト | 502 | `qiita_unavailable` |
| Qiita のレート制限 | 503 | `qiita_rate_limited` |

**409 の意味が増える**ので、画面は `error.code` で分岐する（content-pipeline §6-7 と同じ方針）。

---

## 13. フロントエンド

### 13-1. 画面とルート

| ルート | 画面 | 時期 |
|---|---|---|
| `/projects/[id]/contents/[cid]/publish` | **公開画面**：チャネルのタブ（M1 は Qiita だけ）、変換の実行と状態、原稿の編集、プレビュー、公開・更新、公開物 | M1 |
| `/projects/[id]/publications` | 企画の公開済み一覧 | M1 |
| `/settings/accounts` | Qiita トークンの登録・差し替え・削除 | M1 |
| 編集画面（既存） | ヘッダに［公開へ］のリンクと、公開物があればチャネルのバッジ | M1 |

**公開画面を編集画面と分ける**（`requirements.md` §8 最後の項目）。編集画面はすでにエディタ・プレビュー・履歴で埋まっていて、原稿用にもう1つのエディタとバッファを足すと、どちらのバッファを保存しているのかが画面上で曖昧になる。

### 13-2. 状態の3分類（frontend.md §2）

| 状態 | 置き場所 |
|---|---|
| 公開画面のまとめ（原稿・ジョブ・公開物・最新リビジョン番号） | TanStack Query のキャッシュ（キー `["channel", projectId, contentId, channel]`） |
| 原稿の編集中バッファ | `useState`。キャッシュに入れない（content-pipeline の `useContentWriter` と同じ形。保存は手動＋⌘S。**自動保存はしない**：原稿は公開の直前に1回整える作業で、自動保存の版の細切れが要らない） |
| 公開範囲の選択・確認ダイアログ | ローカル |

- 編集画面と公開画面で TanStack Query を使うのは ADR-0015 追記の「プッシュが来る画面だけ」に沿う。**公開画面は M2 でジョブ進捗の SSE が来る画面**になる
- 企画の公開済み一覧と設定画面は Server Component ＋ Server Action（カンバンと同じ）

### 13-3. 変換の状態の見せ方（M1）

- 実行ボタン → `POST .../conversions`（202）→ キャッシュのジョブを `queued` に差し替える
- ジョブが `queued` / `running` のあいだだけ、**`refetchInterval: 2000`** で公開画面のまとめを取り直す。終わったら止める
- 実行ボタンの近くに「**本文を Claude API（Anthropic）に送って変換します**」と出す（requirements §6 個人情報）
- 失敗したら `error_code` に応じた文言（§8-3）と［再実行］

### 13-4. 公開の操作

- ［Qiita に投稿］→ 確認ダイアログ（公開範囲の選択。既定は**限定共有**。「一般公開は後から限定共有に戻せません」）→ `POST .../publish`
- 原稿に未保存の変更があれば、先に保存するか確認する（content-pipeline の復元と同じ。保存に失敗したら投稿しない）
- 成功したら URL を出し、公開物のキャッシュとコンテンツの状態（`公開済`）を取り直す
- Qiita のトークンが無い（`qiita_token_missing` / `qiita_token_invalid`）なら、設定画面へのリンクを出す
- reviewer / demo / editor には投稿・更新・取消のボタンを出さない（API でも 403）

### 13-5. BFF

既存のパススルー（`app/api/projects/[...path]/route.ts`）で `/projects/...` は中継できる。**`/channels` と `/me/accounts/...` 用のパススルーを足す。** トークンの登録は Server Action からでもよいが、パススルーに揃える（BFF に業務ロジックを持たせない・ADR-0014）。

---

## 14. シーケンス

### 14-1. 変換（M1）

```
画面            BFF/API             ConversionService      DB                 Worker        Claude
 │ 変換を実行 ──▶ POST conversions ─▶ request()
 │                                   ├ authz(WRITE)
 │                                   ├ INSERT job(queued) ─▶ （部分 UNIQUE）
 │ ◀── 202 {job} ◀───────────────────┘ commit ────────────▶
 │ 2秒ごとに取り直す
 │                                                          ◀─ SKIP LOCKED ── claim()
 │                                                          running, commit
 │                                                                            convert() ─▶ stream
 │                                                                                       ◀─ JSON
 │                                                          ◀─ complete() ──
 │                                                          succeeded・原稿へ反映（§9-2）, commit
 │ ── 取り直し ─▶ GET channels/qiita ─▶ succeeded・原稿
 │ 原稿を表示（取り直しを止める）
```

### 14-2. Qiita への新規投稿（M1）

```
画面            API                 PublicationService      DB                   Qiita
 │ 投稿 ───────▶ POST publish ─────▶ publish_qiita()
 │                                   ├ authz(PUBLISH)
 │                                   ├ lock_for_publish ───▶ SELECT FOR UPDATE
 │                                   ├ 状態・既存公開物・原稿 version・制約
 │                                   ├ トークン復号
 │                                   ├ create_item ────────────────────────────▶ POST /items
 │                                   │                      ◀──────────────────── 201 {id, url}
 │                                   ├ INSERT publication, mark_published ─▶ flush
 │ ◀── 201 {publication} ◀───────────┘ commit（ロック解放）
```

---

## 15. テスト方針（C10）

| 層 | 方法 | 主なケース |
|---|---|---|
| Service（実 DB） | content-pipeline と同じく本物の Repository で組み立て、**`FakeConverter` / `FakeQiita` / 固定鍵の `TokenCipher`** を差し込む | 認可（editor は変換できて公開できない、demo はトークン登録不可）、二重実行の 409（部分 UNIQUE）、§9-2 の反映の3分岐、Qiita の制約、新規投稿 → 公開物 → `公開済`、二重投稿の 409、取消 → `drafting`、汎用 API で `published` へ 422 |
| ワーカー | `claim → complete / fail` を直接呼ぶ。ループ自体はテストしない | SKIP LOCKED で2つ目は拾わない、止まったジョブの回収、Claude の各失敗が `error_code` になる |
| `llm/converter.py` | **実際の API は呼ばない。** SDK のクライアントを差し替え、`stop_reason`（refusal / max_tokens）・Schema 不一致・各例外の対応だけ確かめる | §8-3 の表 |
| `channels/qiita.py` | `httpx.MockTransport` | ステータスごとの対応（§10-5）、POST を再試行しない |
| `core/crypto.py` | 往復、鍵の差し替え（古い鍵の暗号文が読める）、改ざんで失敗、例外にトークンが出ない | |
| API 結合 | `TestClient` ＋ fake を deps で差し替え | 変換 → ワーカーを1回回す → 原稿 → 編集 → 投稿 → 公開物 → 更新、401 / 403 / 404 / 409 / 422 |
| OpenAPI | `test_openapi_lists_every_endpoint` に新エンドポイントを足す | |

**ログにトークン・本文が出ないこと**は、`caplog` で確かめる（トークンを含むリクエストを失敗させて、ログ全体に値が無いこと）。

---

## 16. requirements.md との対応

| 受け入れ条件 | 設計 |
|---|---|
| C1 チャネルと capabilities | §2（`channels/capabilities.py`）・§3-2・§6 |
| C2 変換プロファイル | §3-2・§8-2 |
| C3 チャネル変換 | §7・§8 |
| C4 チャネル原稿 | §9 |
| C5 Qiita のトークン | §5・§10-1・§10-2 |
| C6 Qiita への公開 | §10-3〜10-5 |
| C7 intent / manual・貼り戻し（M3） | §11-1 |
| C8 公開物と取消 | §4・§11 |
| C9 タグ提案（M3・任意） | 変換の `tags` 出力（§8-1）の仕組みを流用する。M3 で着手するときに追記する |
| C10 テストと品質 | §15 |

---

## 17. 未決事項の解消状況（`requirements.md` §8）

| 項目 | 解消 |
|---|---|
| M1 の変換をジョブ基盤なしで非同期にする方法 | DB キュー ＋ 同じプロセスの常駐ワーカー（`SKIP LOCKED`）。`JobDispatcher` ポートで M2 に備える。§7・ADR-0017 |
| 再変換で手直しを失わない方式 | 手直し済みなら置き換えず保留にし、結果を並べて選ばせる。§9-2 |
| チャネル原稿の持ち方と変換元の版 | コンテンツ×チャネルで1件。変換元は `source_revision_no`（`contents.version` ではない）。§3-2・§9-3 |
| Qiita への送信と記録の整合 | コンテンツ行のロックで直列化＋部分 UNIQUE。送信後の記録失敗はログと貼り戻しで直す。§10-3 |
| `公開済` からの遷移と、公開物が0件になったとき | 汎用 API からは動かせない。取消で0件になったら `drafting` に戻す。§4 |
| 公開取消の持ち方 | 論理削除。`metrics` は `cancelled_at IS NULL` だけを対象にする。§3-2・§11 |
| Qiita のタグ | 変換で LLM に出させ、既存タグに寄せる。1〜5個。§10-4 |
| トークンの暗号化方式と鍵 | Fernet ＋ MultiFernet、`TOKEN_ENCRYPTION_KEYS`。§10-1 |
| トークンをユーザー単位で持つか | ユーザー単位。Qiita のアカウントは個人のもので、企画の owner が複数いても他人のトークンで投稿しない。§5 |
| 変換プロファイルの持ち方とプロンプト | 企画×チャネル、項目ごとの列。初回の変換で既定値から作る。§3-2・§8-2 |
| モデル・タイムアウト・最大トークン | `claude-opus-5-5`・effort medium・ストリーミング・`max_tokens` 64000・600秒。§8-1 |
| X の文字数の数え方 | **M3 着手時に最新仕様を確認して決める**（持ち越し） |
| チャネル原稿の編集画面の置き場所 | 編集画面とは別の公開画面。§13-1 |

### このスペックで新たに決めたこと

- チャネルの定義はコードに置き、`channels` テーブルは作らない（§3-2）→ **requirements-overview §8 のデータモデルを直す**
- `published` を汎用の遷移表に足さない（§4）→ **foundation の `ALLOWED` のコメントを直す**
- Permission `CONTENT_PUBLISH` を足す（§5）
- `app/llm/` を足す（§2）→ **structure.md を直す**
- 新しい依存：`anthropic`、`cryptography`、`httpx`（dev から本体へ）

---

## 18. 個人情報の扱い

| 観点 | 扱い |
|---|---|
| 保存するもの | Qiita のアクセストークン（暗号化）、Qiita のユーザー名（表示用）。それ以外の Qiita のアカウント情報は保存しない |
| 第三者への送信 | 変換時に本文・タイトル・企画のタグ名を Anthropic（Claude API）へ送る。トークンは Qiita にだけ送る |
| 利用者への明示 | 変換ボタンの近くに送信先を書く（§13-3）。招待制なのでプライバシーポリシーは置かない（product.md） |
| 削除 | トークンは本人がいつでも削除できる（`DELETE /me/accounts/qiita`）。ユーザー削除時は `ON DELETE CASCADE` で消える |
| ログ | トークン・本文・プロンプトを出さない。出すのはジョブ ID・`request_id`・外部 ID・トークン数 |
