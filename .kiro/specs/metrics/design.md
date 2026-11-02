# design.md — metrics（指標の収集・分析）

> **前提**：`requirements.md`（`4405316`）、foundation の design.md（認可・エラー封筒・1リクエスト1トランザクション）、
> publishing の design.md（`publications`・Qiita クライアント・ポートの形・ワーカー）、ADR-0013（PostgreSQL の自前キュー）、ADR-0017（変換の DB キュー）、ADR-0006（SSE）。
> **このドキュメントの範囲**：M2（50h）を詳しく、M3 の性能実測は手順と判定だけ決める。`requirements.md` §8 の未決事項をここで解消する。

---

## 1. 設計の狙い

1. **収集を先に動かす** — 推移は後から復元できない。tasks の順番は「スナップショット → Qiita の日次取得 → RSS」を先にし、画面より前に溜め始める（§15）
2. **キューは ADR-0017 の形を広げる** — `SKIP LOCKED` で拾う・止まった行を回収する・commit はワーカーが持つ。足すのは**リトライの時刻管理**と**冪等な定期投入**だけ（§6）
3. **スナップショットは「公開物×日付で1行・指標ごとの列」** — 1日1行なので集計で縦横の組み替えが要らない。チャネルで取れない指標は NULL（§3・ADR-0008）
4. **集計は SQL で書く** — 累積値から日次の増分を `lag()` で出し、相対日数・タグ・コホートで集約する。アプリで全件を読まない（§9）
5. **外部 API は Service から見てポート** — Qiita・RSS の取得は `app/channels` に置き、Service は Protocol だけを知る（publishing と同じ）

---

## 2. モジュール構成

```
backend/app/
├── modules/metrics/             ★新規
│   ├── models.py        MetricSnapshot / JobRun / JobRunItem / PodcastFeed / PodcastEpisode
│   ├── repository.py    スナップショット・ジョブ・RSS の読み書き
│   ├── analytics.py     分析クエリ（Repository 層。SQL だけを持つ）
│   ├── service.py       SnapshotService / JobService / FeedService / AnalyticsService
│   ├── ports.py         MetricsFetcher / FeedReader / PublicationGateway と入出力の型
│   ├── schemas.py
│   ├── router.py        REST と SSE
│   └── deps.py
├── channels/
│   ├── capabilities.py  ★変更 指標の定義（`metric_fields` / `primary_metric` / `manual_metrics`）を足す
│   ├── qiita.py         ★変更 `get_item_metrics` を足す
│   └── podcast_rss.py   ★新規 RSS の取得と解析（SSRF 対策込み・§8-2）
└── jobs/
    ├── loop.py          ★新規 ポーリングのループ（変換・指標で共通）
    ├── worker.py        変換ワーカー（loop.py を使うように寄せるだけ）
    ├── metrics_worker.py ★新規 指標・RSS のジョブを処理する
    └── scheduler.py     ★新規 定期投入（§6-3）
```

| 判断 | 理由 |
|---|---|
| `modules/metrics` を作る | 収集・分析は公開と変更の理由が別。publishing はすでに大きい |
| 分析クエリを `analytics.py` に分ける | 分析の SQL は長く、書き込みの Repository と混ぜると読みにくい。層は Repository（Service から呼ぶ） |
| 共通にするのは `jobs/loop.py` だけ | ADR-0013「共通にするのは拾い方だけ」。ループ（ポーリング間隔・1周の失敗でループを止めない・キャンセル）は同じで、**拾う SQL は各モジュールの Repository に置く**（テーブルが違う） |
| 公開物の読み書きは `PublicationGateway` 経由 | RSS からの公開物の作成は publishing の持ち物（二重登録の制約・`公開済` への遷移）。metrics が `publications` に直接 INSERT しない |
| 分析クエリは `publications` / `contents` / `content_tags` を読む | 集計の JOIN を Gateway 越しにすると N+1 になる。**読むだけ**で、書き込みは必ず Gateway を通す |

### `.importlinter` の変更

- `layers` / `service-no-sqlalchemy` / `service-no-fastapi` に `app.modules.metrics` を足す
- **新しい契約**：`app.modules.metrics.service` は `app.channels.qiita` / `app.channels.podcast_rss` / `httpx` を import しない（ポートだけを知る）
- 既存の「`app.jobs` は `*.repository` を import しない」に `metrics_worker` / `scheduler` も含まれる（`app.jobs` 全体が対象なのでそのまま）

---

## 3. データモデル

### 3-1. ER 図（このスペックで足す部分）

```
projects
  ├─ podcast_feeds                 企画に1つ（UNIQUE project_id）
  │    url, registered_by, last_fetched_at, last_error
  │     └─ podcast_episodes        見たエピソードの記録（取消後の復活防止）
  │          guid, publication_id
  │
  ├─ job_runs                      ジョブ1回＝1行。履歴と SSE の単位
  │    kind, trigger, target_date, status, requested_by,
  │    total / succeeded / failed, started_at, finished_at, error_code, error_message
  │     └─ job_run_items           キューの1件（公開物1件・RSS 1回）
  │          publication_id?, status, attempts, next_run_at, error_code, error_message
  │
  └─ publications（publishing）
       └─ metric_snapshots         ★公開物×対象日で1行（PK）
            project_id, channel, captured_on, source,
            views, likes, stocks, comments, captured_at, updated_by
```

### 3-2. `metric_snapshots`（ADR-0008 に残す）

| 項目 | 決定 | 理由 |
|---|---|---|
| **持ち方** | **横持ち**：指標ごとの列 `views` / `likes` / `stocks` / `comments`（`bigint NULL`） | 1日1行なので、推移・増分・集計で行を組み替える必要が無い。縦持ち（指標名×値）は行数が4倍になり、どの集計にも `pivot` が要る。チャネルで取れない指標は NULL |
| 指標の意味 | 列は汎用、**チャネルごとの意味と表示名は capabilities に置く**（§4） | 例：`views` は Qiita なら閲覧数、X ならインプレッション、ポッドキャストなら再生数。指標の種類を足すたびに列を足すより、Phase 1 の4列で全チャネルが収まる |
| 主キー | `(publication_id, captured_on)` | 「公開物×日で1行」を DB で保証する。上書きは `INSERT ... ON CONFLICT DO UPDATE` |
| `project_id` / `channel` | **公開物から写して持つ**（非正規化） | ダッシュボードの「企画×直近30日」を `publications` と JOIN せずに引ける。公開物の企画・チャネルは変わらないのでずれない |
| `captured_on` | `date`。JST の日付 | requirements S1 |
| `source` | `auto` / `manual`。**行単位** | チャネルの指標は「全部自動」か「全部手入力」のどちらかしか無い（§4）。値ごとに持つ必要が無い |
| `captured_at` / `updated_by` | 取得した時刻（UTC）／手入力した人（自動なら NULL） | 手入力の出どころを追えるように |
| ロールアップ・パーティション | **M2 では作らない。** M3 の実測で目標を外したら、月次のマテリアライズドビューを足す | 50万行は PostgreSQL にとって小さい。測る前に作らない（requirements-overview §12「着手前に削らない・測ってから判断」と同じ考え方） |

### 3-3. ジョブ

| 項目 | 決定 | 理由 |
|---|---|---|
| **2段にする** | `job_runs`（実行1回・画面と SSE の単位）＋ `job_run_items`（キューの1件・リトライの単位） | 1回の日次取得で公開物が100件あり、**失敗した1件だけをリトライしたい。** 1テーブルで公開物ごとに1行にすると「1回の実行で何件中何件」（S4）を毎回集めることになる |
| `kind` | `qiita_metrics` / `podcast_rss` | チャネルの分岐は capabilities を見る。`kind` は「何の処理か」で、取得元ごとに1つ |
| `trigger` | `scheduled` / `manual` / `retry` | 再実行は新しい `job_runs` として作り、元の行は書き換えない（S4） |
| `target_date` | JST の日付。手動実行でも「今日」 | 同じ日の手動実行は同じ日のスナップショットを上書きする（S1） |
| `requested_by` | 手動・再実行はその人。**定期実行は NULL** | §5-2 |
| `status`（run） | `queued` → `running` → `succeeded` / `partially_failed` / `failed` | items の結果から決める。1件でも確定失敗があれば `partially_failed` |
| `status`（item） | `queued` → `running` → `succeeded` / `failed`。リトライ待ちは `queued` のまま `next_run_at` を未来にする | 「拾ってよい」の条件を `status = 'queued' AND next_run_at <= now()` の1つにする |
| `attempts` / `next_run_at` | item に持つ | §6-2 |
| 件数 | `total` / `succeeded` / `failed` を run に持ち、item が確定するたびに同じトランザクションで足す | SSE が毎秒 `COUNT(*)` しなくて済む |

### 3-4. 制約とインデックス

| テーブル | 制約・インデックス | 目的 |
|---|---|---|
| `metric_snapshots` | PK `(publication_id, captured_on)` | 1日1行・上書き |
| `metric_snapshots` | インデックス `(project_id, captured_on)` | ダッシュボードの直近30日 |
| `metric_snapshots` | CHECK 各列 `>= 0` | 負の値を DB でも止める |
| `metric_snapshots` | 複合 FK `(publication_id, project_id) → publications(id, project_id)` | 企画をまたぐ参照を止める（publishing §3-3 と同じ） |
| `job_runs` | **部分 UNIQUE `(project_id, kind, target_date) WHERE trigger = 'scheduled'`** | 定期投入はプロセスが複数あっても1回（S2・ADR-0013） |
| `job_runs` | **部分 UNIQUE `(project_id, kind) WHERE status IN ('queued', 'running')`** | 同じ企画で同じ種類が二重に走らない。手動実行の 409（S4） |
| `job_runs` | インデックス `(project_id, created_at DESC)` | 実行履歴の一覧 |
| `job_run_items` | 部分インデックス `(next_run_at) WHERE status = 'queued'` | ワーカーが拾う |
| `podcast_feeds` | UNIQUE `(project_id)` | 企画に1つ |
| `podcast_episodes` | UNIQUE `(feed_id, guid)` | 同じエピソードを二度登録しない。**取消した公開物の分も行が残る**ので復活しない（S6） |

> 定期実行の部分 UNIQUE と「二重に走らない」の部分 UNIQUE は衝突しうる（手動実行が走っている時刻に定期投入が来る）。そのときは定期投入を**その周回では見送り**、次の周回で入れる（§6-3）。

---

## 4. capabilities の拡張

`Capabilities` に指標の定義を足す。**画面・Service・SQL は指標名で分岐せず、ここを見る。**

```python
@dataclass(frozen=True)
class MetricField:
    column: Literal["views", "likes", "stocks", "comments"]
    label: str            # 画面の表示名

@dataclass(frozen=True)
class Capabilities:
    ...
    metrics: MetricsMode                  # 既存：auto / manual / none
    metric_fields: tuple[MetricField, ...]  # このチャネルで意味のある列
    primary_metric: str                   # 分析の代表指標（§9-1）
```

| チャネル | `metrics` | 列と表示名 | 代表指標 |
|---|---|---|---|
| Qiita | auto | likes＝LGTM、stocks＝ストック、comments＝コメント、views＝閲覧数（取れれば） | likes |
| X | manual | views＝インプレッション、likes＝いいね | views |
| note | manual | views＝ビュー、likes＝スキ、comments＝コメント | likes |
| ポッドキャスト | manual | views＝再生数 | views |

- **`metrics = manual` のチャネルだけ手入力を受ける。** auto のチャネルへの手入力は 422（S7「自動取得した値は手入力で上書きしない」をチャネル単位で満たす）
- ポッドキャストは RSS で公開物を自動で登録するが、指標（再生数）は手入力。`metrics = manual` のままでよい（RSS は公開物の登録で、指標の取得ではない）
- Qiita の閲覧数が取れなかった日は `views = NULL`（§7-1）

---

## 5. 認可

### 5-1. Permission の追加

| Permission | owner | editor | reviewer | demo | 使う操作 |
|---|:---:|:---:|:---:|:---:|---|
| `PROJECT_VIEW`（既存） | ○ | ○ | ○ | ○ | 指標・ダッシュボード・分析・ジョブ履歴・SSE の閲覧 |
| `METRICS_INPUT` ★ | ○ | ○ | × | × | 指標の手入力 |
| `METRICS_COLLECT` ★ | ○ | × | × | × | 手動実行・再実行・RSS の登録／変更／削除 |

`METRICS_COLLECT` を `CONTENT_PUBLISH` と分けるのは、**意味の違う操作に同じ権限を使い回すと、片方だけ変えたいときに分けられなくなる**ため。今は持っているロールが同じ。

### 5-2. ジョブの中の認可

| ジョブ | 誰として動くか | 理由 |
|---|---|---|
| 指標の取得（手動・再実行） | 投入時に `requested_by` の `METRICS_COLLECT` を確認済み。**ワーカーは読み取りとスナップショットの書き込みだけ**なので通し直さない | スナップショットの書き込みはユーザーの操作ではなく、取得結果の記録 |
| 指標の取得（定期） | **システム**（`requested_by = NULL`）。`cli.py` の bootstrap と同じく、Service の外から呼ぶ専用の入口 `SnapshotService.record_fetched()` を使う | 定期実行には操作した人がいない。この入口はスナップショットを書くだけで、HTTP からは呼べない（router に出さない） |
| RSS の取り込み | **RSS を登録した owner（`podcast_feeds.registered_by`）として認可を通し直す** | コンテンツと公開物を作る＝公開の操作。登録した人が owner でなくなっていたら、取り込みは `forbidden` で確定失敗にする（リトライしない） |

Qiita のトークンは**その公開物を公開したユーザー**（`publications.published_by`）のものを使う。

---

## 6. ジョブの実行

### 6-1. 全体の流れ

```
scheduler（ループのたび）          API（手動実行・再実行）
  └ 今日の分が無ければ投入            └ JobService.request_run()
      job_runs(scheduled) +              ├ 認可（METRICS_COLLECT）
      job_run_items × 公開物             ├ job_runs(manual) + items
                                         └ 202 → commit
                     ↓
metrics_worker（jobs/loop.py のループ・2秒ごと）
  ├ ① 回収：running のまま 10分を超えた item を queued に戻す（attempts は増やさない）
  ├ ② 拾う：別セッションで
  │     SELECT ... FROM job_run_items
  │     WHERE status='queued' AND next_run_at <= now()
  │     ORDER BY next_run_at LIMIT 1 FOR UPDATE SKIP LOCKED
  │     → running・attempts+1・（run が queued なら running に）→ commit
  ├ ③ 取得：DB の外で Qiita / RSS を呼ぶ
  └ ④ 書く：別セッションで
        成功 → スナップショットを UPSERT、item を succeeded、run の件数を更新
        失敗 → §6-2 でリトライか確定失敗かを決める
        全 item が確定 → run を succeeded / partially_failed / failed
        → commit
```

- 変換ワーカーと同じく、②と④の間で DB の接続もロックも持たない
- ワーカーは**変換と指標で別の asyncio タスク**にする（変換が数分かかっている間に指標の取得が止まらないように）。どちらも `jobs/loop.py` の `run_forever` を使う
- 設定 `RUN_METRICS_WORKER`（既定 `true`）。テストでは `false` にし、`run_once` を直接呼ぶ

### 6-2. リトライ

| 失敗 | 扱い |
|---|---|
| タイムアウト・接続エラー・5xx | リトライする |
| 429（レート制限） | リトライする。`next_run_at` は **`Rate-Reset` ヘッダの時刻**（無ければ 15分後）。**attempts を増やさない**（制限は失敗ではない） |
| 401 / 403（トークン無効）・トークンが無い | **リトライしない**（繰り返しても直らない）。`error_code = qiita_token_invalid` / `qiita_token_missing` |
| 404（Qiita で記事が消された） | **リトライしない**。`qiita_item_missing`。公開取消を案内する |
| 認可の失敗（RSS を登録した人が owner でない） | **リトライしない**。`forbidden` |
| RSS の形式が読めない | リトライする（一時的に壊れた配信の可能性がある） |
| 想定外の例外 | リトライする（`internal_error`） |

- **上限 5回**。間隔は `1分 × 4^(attempts-1)`（1分・4分・16分・64分）に、±20% の揺らぎを足す。合計で約1.5時間あれば、Qiita の一時的な障害はたいてい越えられる
- 上限に達したら `failed` で確定し、`error_code` / `error_message` / 時刻を残す（S3）
- 回収（§6-1 ①）は 10分。1件の取得は数秒（タイムアウト 15秒）なので、生きている実行を回収しない

### 6-3. 定期投入（scheduler）

- metrics_worker のループの中で、**60秒に1回** `scheduler.tick()` を呼ぶ（別のタスク・別のプロセスにしない）
- `tick()`：JST の現在時刻が **05:00 以降**なら、今日の `target_date` で、**指標を取るべき企画ごと**に `job_runs(scheduled)` を INSERT する
  - `qiita_metrics`：`metrics = auto` のチャネルに、取り消されていない公開物を持つ企画
  - `podcast_rss`：`podcast_feeds` を持つ企画
- **INSERT は `ON CONFLICT DO NOTHING`**（部分 UNIQUE `(project_id, kind, target_date) WHERE trigger = 'scheduled'`）。プロセスが複数あっても、何度 tick しても1回しか入らない
- 同じ企画で手動実行が走っていて「二重に走らない」の制約に当たったら、その周回は見送る（次の tick で入る）
- ワーカーが止まっていて 05:00 を過ぎても、起動後の最初の tick で今日の分が入る。**前日以前の分はさかのぼらない**（S2・外部 API は今の値しか返さない）
- 05:00 にするのは、前日の反応が出そろってから取り、`captured_on` を「その日の朝の値」にそろえるため

### 6-4. レート制限

- Qiita の制限は**認証付きで1時間あたり1000リクエスト（トークンごと）**（API ドキュメントで確認・2026-11-03）。公開物1件につき1リクエストで、Phase 1 の公開物は約110件なので、1日1回では制限の1割程度にしかならない
- それでも**チャネルごとに呼び出しの間に最低1秒あける**（`QiitaClient` が直前の呼び出し時刻を持つ）。ワーカーは item を1件ずつ処理するので、プロセス内の同時実行は常に1本
- 429 が来たら §6-2 の扱いで、**同じチャネルの残りの item も `Rate-Reset` まで後ろにずらす**（同じトークンで叩き続けない）
- 複数プロセスで同じトークンを使ったときの合算は制御しない。Phase 1 は1プロセスで、上の数字なら合算しても届かない。プロセスを増やすときに見直す（§17）

---

## 7. Qiita の指標

### 7-1. 取り方

- `GET /api/v2/items/:item_id` を、公開した人のトークンで呼ぶ。応答の `likes_count` / `stocks_count` / `comments_count` / `page_views_count` を `likes` / `stocks` / `comments` / `views` に写す
- **`page_views_count` は NULL になりうる**（API ドキュメントでは `null, integer`）。自分の記事で認証付きなら取れる想定だが、ドキュメントに条件が書かれていないので**実機で確かめる**（tasks の実機確認）。NULL なら `views = NULL` で保存する（0 にしない）
- 限定共有の記事が、この API で取れるかも実機で確かめる。取れなければ `qiita_item_missing` と区別できる `error_code` を足す
- 一覧 API（`/authenticated_user/items`）で100件ずつまとめて取る案は採らない：`page_views_count` が一覧で返るか分からず、公開した人ごと・公開物ごとに失敗を分けたい（リトライの単位が item）ため。110件では1件ずつで足りる
- 応答のうち指標以外（本文・コメントの中身）は保存しない（requirements §6 個人情報）

### 7-2. ポート

```python
class MetricsFetcher(Protocol):
    async def fetch(self, token: str, external_id: str) -> FetchedMetrics: ...

@dataclass(frozen=True)
class FetchedMetrics:
    views: int | None
    likes: int | None
    stocks: int | None
    comments: int | None
```

例外は publishing の `QiitaAuthError` / `QiitaNotFoundError` / `QiitaRateLimitedError`（`reset_at` を足す）/ `QiitaUnavailableError` をそのまま使う。

---

## 8. ポッドキャスト RSS

### 8-1. 取り込み

1. owner が RSS の URL を登録する → **その場で1回取得して形式を確かめる**（読めなければ 422 `invalid_feed`）→ `podcast_feeds` を作り、`podcast_rss` のジョブを1件投入する（既存エピソードの取り込み・S6）
2. ジョブは RSS を取得し、`<item>` ごとに：
   - 識別子 = `<guid>`。**無ければ `<enclosure url>`、それも無ければ `<link>`**。どれも無い item は飛ばしてログに残す
   - `podcast_episodes` に `(feed_id, guid)` が**あれば何もしない**（取消済みでも行が残るので復活しない）
   - 無ければ `PublicationGateway.register_episode()` で、コンテンツ（`公開済`・タイトル＝エピソード名）と公開物（ポッドキャスト・URL＝`<link>`・公開日時＝`<pubDate>`）を作り、`podcast_episodes` に記録する。**ここまでを1トランザクション**にする
3. RSS の取得は1件の item（`publication_id = NULL`）として扱い、§6-2 のリトライに乗る

### 8-2. 取得の安全性（SSRF）

RSS の URL は利用者が入力し、**サーバーがそこへアクセスする**。publishing の貼り戻し（URL にアクセスしない）と違い、内部ネットワークへの踏み台になりうる。

- `https` だけを受ける
- 名前解決した IP が**プライベート・ループバック・リンクローカル・予約済み**（`ipaddress` の `is_private` / `is_loopback` / `is_link_local` / `is_reserved`）なら拒否する。AWS のメタデータ（`169.254.169.254`）もここで止まる
- **リダイレクトは自動で追わない。** 最大3回まで、行き先ごとに上の検証をやり直してから追う
- 応答は **5MB まで**読み、超えたら打ち切る。タイムアウト 15秒
- XML は **`defusedxml`** で解析する（外部実体・エンティティ展開の攻撃を止める）
- 名前解決と接続の間に IP がすり替わる（DNS rebinding）のを防ぐため、**検証した IP に直接接続し、`Host` ヘッダと SNI に元のホスト名を使う**

### 8-3. `公開済` への遷移との両立

publishing C8「`公開済` への遷移は公開操作からだけ起きる」は、**RSS の取り込みを公開操作の1つとして扱う**ことで守る。

- `PublicationService.register_episode(actor, project_id, ...)` を publishing に足す。`CONTENT_PUBLISH` を確認し、`ContentGateway` でコンテンツを作って `mark_published` する（遷移ログに `drafting → published` が残る）
- 汎用の状態遷移 API の制限（`公開済` へは進めない）はそのまま

### 8-4. エピソードを既存のネタにまとめる（M2・任意）

公開物の `content_id` を付け替える。元のコンテンツに公開物が残らなければ、そのコンテンツは削除する（RSS が作った、本文の無いコンテンツのため）。時間が足りなければ Phase 2 に回す。

---

## 9. 分析

### 9-1. 基本の考え方

- スナップショットは**累積値**（その日の時点の総数）。日次の増分は `value - lag(value) OVER (PARTITION BY publication_id ORDER BY captured_on)` で出す
- **欠測の日をまたいだ増分は、次に取れた日にまとめて計上する**（日数で割って均さない）。グラフでは欠測の日に点を打たない
- **チャネルを混ぜて集計しない。** 分析は必ずチャネルを1つ選び、そのチャネルの**代表指標**（§4 の `primary_metric`）で比べる
- 公開日は `publications.published_at` を JST の日付にしたもの。**公開後 N 日 = `captured_on - 公開日`**
- 取り消した公開物は、分析・ダッシュボードから**外す**（スナップショットは残る）

### 9-2. 各クエリ

| 画面の要素 | クエリの形 | 要件 |
|---|---|---|
| 直近30日の推移 | 企画×チャネル×日で、代表指標の**日次増分の合計**。`generate_series` で30日分の日付を作り LEFT JOIN（空の日も並ぶ） | S8 |
| Top5 | 代表指標の**直近7日の増加量**（最新値 − 7日前以前で最も近い値）で並べる。公開から7日未満なら公開時点を0とする | S8 |
| ネタ在庫のサマリ | `contents` を状態ごとに `COUNT` | S8 |
| 公開物の推移 | その公開物のスナップショットを日付順（累積値と増分の両方） | S9 |
| **公開後 N 日の伸びカーブ** | 公開物ごとに `(N, 代表指標の累積値)`。N は 0〜90。比べる公開物は最大10件まで画面で選ぶ（既定は直近の10件） | S10 |
| **タグ別** | 公開後30日時点の代表指標（30日目が欠測なら、それ以前で最も近い日）を公開物ごとに出し、タグで `avg` と `percentile_cont(0.5)`。**公開から30日未満は対象外** | S10 |
| **公開月コホート** | 公開月ごとに、公開後 0〜12か月の各月末時点の累積値の合計 | S10 |
| 曜日別 | タグ別と同じ値を、公開日の曜日（JST）で集約 | S10 |
| 文字数帯別 | タグ別と同じ値を、`contents.body_md` の文字数で 〜2,000 / 〜5,000 / 〜10,000 / それ以上に分けて集約 | S10 |

- 文字数は**チャネル原稿ではなく本文**（`contents.body_md`）で数える。チャネル原稿が無いチャネル（ポッドキャスト）もあり、条件をそろえるため。本文が空（RSS で作ったコンテンツ）は対象外
- 「30日」「7日」「90日」は定数にし、画面から変えられるようにはしない（Phase 1）

### 9-3. 分析画面を統合したとき（削る順番の1番目）

分析画面（§12 の `/metrics/analysis`）を作らず、**伸びカーブ・タグ別・コホートの3つをダッシュボードのパネル**にする。クエリと API はそのまま使い、曜日別・文字数帯別の API と画面を作らない。**API とクエリを先に作り、画面を後に作る**ので、11月中旬の判断はどちらに倒しても作業が無駄にならない。

---

## 10. SSE

### 10-1. FastAPI

- `GET /projects/{id}/job-runs/{run_id}/events`（`text/event-stream`）
- 最初に通常のセッションで**認可（`PROJECT_VIEW`）と、その run が企画のものかを確かめる**（他企画なら 404）。そのあとストリームの中では**リクエストのセッションを使わず**、1秒ごとに短いセッションを開いて `job_runs` を読む（ストリームの間ずっと接続を持たない）
- 状態が変わったときだけ `event: progress`（`{status, total, succeeded, failed}`）を送る。確定したら `event: done` を送って閉じる
- 15秒ごとにコメント行（`: keep-alive`）を送る（途中のプロキシに切られないように）
- **接続直後に必ず現在の状態を1回送る**。再接続（`Last-Event-ID`）でも同じなので、再接続の特別な処理は要らない（S5）

### 10-2. 伝え方：DB のポーリングを選ぶ

| 案 | 判断 |
|---|---|
| **DB を1秒ごとに読む** | **採用。** ワーカーが別プロセスでもそのまま動く。見る人は同時に1〜2人で、主キーで1行読むだけ |
| Postgres の `LISTEN/NOTIFY` | 見送り。SSE の接続ごとに専用の DB 接続を持ち続ける必要があり、SQLAlchemy のプールの外で接続を管理することになる。進捗の更新は数秒に1回で、1秒の遅れは問題にならない |

正は `job_runs` の状態で、SSE は表示を速くするだけ（S5）。

### 10-3. BFF（Next.js）

- 既存のパススルー（`lib/api/passthrough.ts`）は応答を `Response.json` で組み立て直すので**ストリームを中継できない。** SSE 専用の Route Handler を足す：`app/api/streams/projects/[id]/job-runs/[runId]/route.ts`
- Cookie → `Authorization: Bearer` に載せ替えて FastAPI へ `fetch` し、**`upstream.body`（ReadableStream）をそのまま `new Response()` に渡す**（Next.js 16 の Route Handler でのストリーミング・`node_modules/next/dist/docs/01-app/02-guides/streaming.md` で確認）
- ヘッダ：`Content-Type: text/event-stream`、`Cache-Control: no-cache`、`X-Accel-Buffering: no`（途中のプロキシにバッファさせない）
- ブラウザが切断したら（`request.signal`）、FastAPI への `fetch` も中断する
- `/api/projects/[...path]` のキャッチオールと衝突しないよう、**`/api/streams/` に分ける**
- 業務判断はしない（ADR-0014）。パスのセグメントの検証はパススルーと同じ関数を使う

---

## 11. API 一覧

| メソッド | パス | 権限 | 説明 |
|---|---|---|---|
| GET | `/projects/{id}/metrics/dashboard?channel=` | VIEW | 直近30日・Top5・在庫サマリ・最終取得日時・直近の失敗 |
| GET | `/projects/{id}/publications/{pub_id}/snapshots` | VIEW | 公開物の推移 |
| PUT | `/projects/{id}/publications/{pub_id}/snapshots/{date}` | INPUT | 手入力（上書き）。auto のチャネルは 422 |
| GET | `/projects/{id}/metrics/curves?channel=&publication_ids=` | VIEW | 公開後 N 日の伸びカーブ |
| GET | `/projects/{id}/metrics/by-tag?channel=` | VIEW | タグ別 |
| GET | `/projects/{id}/metrics/cohorts?channel=` | VIEW | 公開月コホート |
| GET | `/projects/{id}/metrics/by-weekday?channel=` | VIEW | 曜日別（統合時は作らない） |
| GET | `/projects/{id}/metrics/by-length?channel=` | VIEW | 文字数帯別（統合時は作らない） |
| GET | `/projects/{id}/job-runs` | VIEW | 実行履歴（新しい順・ページング） |
| GET | `/projects/{id}/job-runs/{run_id}` | VIEW | 1回分と、失敗した item の一覧 |
| POST | `/projects/{id}/job-runs` | COLLECT | 手動実行（`{kind}`）。202。走っていれば 409 |
| POST | `/projects/{id}/job-runs/{run_id}/retry` | COLLECT | 失敗した item だけで新しい run を作る。202 |
| GET | `/projects/{id}/job-runs/{run_id}/events` | VIEW | SSE |
| GET / PUT / DELETE | `/projects/{id}/podcast-feed` | VIEW / COLLECT | RSS の取得・登録（変更）・削除 |

---

## 12. フロントエンド

### 12-1. 画面とルート

| ルート | 画面 | データ |
|---|---|---|
| `/projects/[id]/metrics` | **ダッシュボード**（チャネルのタブ・直近30日・Top5・在庫サマリ・最終取得） | Server Component |
| `/projects/[id]/metrics/analysis` | **分析**（伸びカーブ・タグ別・コホート・曜日別・文字数帯別）。統合時は作らない | Server Component（伸びカーブの公開物の選択だけ Client） |
| `/projects/[id]/publications/[pubId]` | 公開物の推移グラフ・手入力フォーム | Server Component ＋ Server Action（手入力） |
| `/projects/[id]/jobs` | 実行履歴・手動実行・再実行・進捗・RSS の登録 | **TanStack Query ＋ SSE** |
| 既存のプロジェクト画面・公開済み一覧 | ダッシュボードへのリンク、公開物から推移へのリンク | — |

- TanStack Query を使うのは**ジョブ画面だけ**（ADR-0015 追記「プッシュが来る画面だけ」）。SSE の `progress` でキャッシュの run を差し替える。ダッシュボードはプッシュが来ないので Server Component
- SSE はブラウザの `EventSource` で `/api/streams/...` に繋ぐ（同一オリジンなので Cookie が付く）

### 12-2. グラフライブラリ：Recharts

| 案 | 判断 |
|---|---|
| **Recharts** | **採用。** 折れ線・棒・欠測（`connectNulls={false}`）が宣言的に書ける。React のコンポーネントとして書けるので、状態の3分類（frontend.md §2）の外に別の状態を持たない |
| Chart.js（react-chartjs-2） | 見送り。canvas に命令的に描くので、React の描画と二重になる |
| visx / D3 | 見送り。自由度は高いが、このプロジェクトでグラフの描画は設計の対象ではない（tech.md「設計の対象でない領域は既製品を使う」） |

- **React 19 に対応した版を入れる**（入れる時点で最新を確かめる）。グラフは Client Component にし、Server Component から整形済みの配列を渡す
- 色はチャネルごとに固定し、Tailwind のデザイントークンに置く（ADR-0015）
- 選定は frontend.md §「未決」のグラフライブラリの項目に反映する

---

## 13. エラー体系（追加分）

| 状況 | HTTP | `error.code` |
|---|---|---|
| 同じ企画で同じ種類のジョブが待機中・実行中 | 409 | `job_in_progress` |
| 再実行しようとした run に失敗した item が無い | 422 | `nothing_to_retry` |
| auto のチャネルに手入力した | 422 | `metrics_not_manual` |
| そのチャネルに無い指標を手入力した | 422 | `invalid_metric` |
| 未来の日付・公開日より前・負の値 | 422 | `invalid_snapshot` |
| RSS が読めない・形式が違う・https でない・内部アドレス | 422 | `invalid_feed` |

ジョブの item の `error_code` は publishing の Qiita のコード（`qiita_token_invalid` 等）と `feed_unavailable` / `forbidden` / `internal_error` を使う。

---

## 14. シーケンス

### 14-1. 定期実行（Qiita）

```
scheduler.tick()（05:00 以降・60秒ごと）
  → 企画ごとに INSERT job_runs(scheduled, today) ON CONFLICT DO NOTHING
  → 入ったら items を公開物ぶん INSERT → commit
metrics_worker
  → item を拾う（SKIP LOCKED）→ running → commit
  → QiitaClient.get_item_metrics(公開した人のトークン, external_id)   ← DB の外
  → 成功：UPSERT metric_snapshots(pub, today) / item succeeded / run の件数 → commit
  → 429：同じチャネルの残り item の next_run_at を Rate-Reset へ → commit
  → 5xx：attempts < 5 なら next_run_at を延ばして queued → commit
```

### 14-2. 手動実行と進捗

```
ブラウザ ─POST /api/projects/1/job-runs─▶ BFF ─▶ FastAPI：認可・INSERT（409 なら終了）→ 202 {run_id}
ブラウザ ─EventSource /api/streams/projects/1/job-runs/{run_id}─▶ BFF ─fetch(stream)─▶ FastAPI
FastAPI：認可 → 現在の状態を送る → 1秒ごとに job_runs を読み、変わったら progress → done で閉じる
```

---

## 15. テスト方針（S12）

| 対象 | 確かめること |
|---|---|
| SnapshotService | 同日の上書き・auto への手入力 422・未来日／公開日前／負の値 422・reviewer の 403・他企画の 404・取消後の公開物を定期の対象から外す |
| JobService | 手動実行の 409・再実行が失敗 item だけを含む新しい run を作り、元の run を書き換えない・editor の 403 |
| scheduler | **同じ日に何度 tick しても run は1件**・05:00 前は入らない・手動実行中は見送る |
| metrics_worker | リトライの間隔と上限・401／404 でリトライしない・429 で attempts を増やさず同じチャネルを後ろにずらす・止まった item の回収・run の最終状態 |
| RSS | guid／enclosure／link の順の識別・二度登録しない・取消後に復活しない・SSRF（プライベート IP・リダイレクト先の検証・サイズ上限）・`defusedxml` で外部実体を拒否 |
| analytics | **小さな既知のデータ（欠測を含む）で、増分・Top5・伸びカーブ・タグ別の中央値・コホートの値が期待どおり** |
| SSE | 他企画の run は 404・接続直後に現在の状態・`done` で閉じる |
| 結合 | 手動実行 → `run_once` → スナップショット → ダッシュボード。401 / 403 / 404 / 409 / 422 |

- Qiita・RSS は `httpx.MockTransport` と fake のポートで再現し、実際に呼ばない
- 時刻は注入できるようにする（`scheduler.tick(now)`、リトライの揺らぎは乱数を注入）

### 15-1. 性能の実測（M3・S11）

- `python -m app.cli seed-metrics --rows 500000`（開発 DB だけ。`APP_ENV=production` では拒否する）
- ダッシュボードと分析の各 API の SQL を `EXPLAIN (ANALYZE, BUFFERS)` で測り、インデックスの有無で Before/After を README に載せる
- 目標（1秒・2秒）を外したら、月次のマテリアライズドビュー（§3-2）を足して測り直す → ADR-0008 に追記

---

## 16. requirements.md との対応

| ストーリー | 主な節 |
|---|---|
| S1 スナップショット | §3-2・§3-4 |
| S2 日次の自動取得 | §6-1・§6-3・§7 |
| S3 リトライ・レート制限 | §6-2・§6-4 |
| S4 実行履歴と手動実行 | §3-3・§11・§12 |
| S5 SSE | §10 |
| S6 RSS | §8 |
| S7 手入力 | §4・§11 |
| S8〜S10 ダッシュボード・推移・分析 | §9・§12 |
| S11 性能 | §3-2・§15-1 |
| S12 テスト | §15 |

---

## 17. 未決事項の解消状況（`requirements.md` §8）

- [x] スナップショットの持ち方 → **横持ち・指標ごとの列・公開物×日の PK**（§3-2）。ADR-0008 に書く
- [x] 手入力と自動取得 → **同じ行・行単位の `source`。チャネル単位でどちらか**（§3-2・§4）
- [x] `job_runs` のカラムと粒度 → **run（実行1回）と item（公開物1件）の2段**（§3-3）
- [x] 定期実行の時刻と仕組み → **JST 05:00 以降・ワーカーのループで60秒ごとに tick・部分 UNIQUE で冪等**（§6-3）
- [x] リトライの上限と間隔 → **5回・1分×4^n・±20%**、リトライしない失敗の分類（§6-2）
- [x] Qiita のレート制限と取れる指標 → **1000回／時（認証付き）。1件ずつ・1秒間隔**。閲覧数と限定共有は実機で確かめる（§6-4・§7-1）
- [x] SSE の伝え方と BFF → **DB を1秒ごとに読む・専用の Route Handler でストリームを中継**（§10）
- [x] RSS の登録先と識別子 → **企画に1つ・guid → enclosure → link**（§8-1）
- [x] RSS 由来の `公開済` → **RSS の取り込みを公開操作として扱い、publishing に `register_episode` を足す**（§8-3）
- [x] 「伸びている」の定義 → **代表指標の直近7日の増加量**（§9-2）
- [x] 文字数帯と文字数の取り方 → **本文の文字数・4区分**（§9-2）
- [x] 代表指標 → **capabilities の `primary_metric`**（§4）
- [x] グラフライブラリ → **Recharts**（§12-2）
- [x] 画面の構成 → §12-1

### このスペックで新たに決めたこと

- RSS の取得は SSRF の対策を必須にする（§8-2）。requirements には無かったが、サーバーが利用者の入力した URL にアクセスするのはこの機能が初めて
- `METRICS_COLLECT` を `CONTENT_PUBLISH` と分ける（§5-1）
- 定期実行はシステムとして動き、スナップショットの書き込みだけの専用の入口を持つ（§5-2）

### 実装時に確かめること

- Qiita：`page_views_count` が自分の記事で取れるか・限定共有の記事を `GET /items/:id` で取れるか・レート制限の応答ヘッダの名前（publishing tasks 6.8 の実機確認と一緒に行う）
- Recharts の React 19 対応版
- 複数プロセスにするときは、同じトークンの合算のレート制限を見直す（§6-4）

---

## 18. 個人情報の扱い

requirements §6 のとおり。設計で足したものは無い。RSS の取得で保存するのはエピソードのタイトル・URL・公開日時・識別子だけで、説明文・音声のファイルは保存しない。
