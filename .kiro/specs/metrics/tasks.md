# tasks.md — metrics（指標の収集・分析）

> **前提**：`requirements.md`（`4405316`）・`design.md`（`57dd777`）は承認済み。
> **範囲**：**M2（約 50h）。** 性能の実測（S11 の【M3】）は §10 に分けて置き、M3 で着手する。
> **進め方**：**収集を先に動かす**（`design.md` §1）。推移は後から復元できないので、
> 「スナップショット → ワーカー → Qiita の日次取得」を通して**溜め始めてから**、RSS・手入力・分析・画面に進む。
> 分析は **API とクエリを先、画面を後**（§9-3）。11月中旬の判断（§7.0）をどちらに倒しても作業が無駄にならない。
> Service / Repository のユニットテストを併走させる（`design.md` §15）。
> **1サブタスク完了ごとにコミット**し、ユーザーにプッシュを促す。

## 0. 実装前の整備

- [x] 0.1 ADR-0008「指標スナップショットのテーブル設計と性能」を書く（横持ち・公開物×日の PK・`project_id` / `channel` の非正規化・ロールアップとパーティションは M3 の実測まで作らない）。`docs/adr/README.md` の索引を「採用」に直す
- [x] 0.2 steering：structure.md に `modules/metrics`・`jobs/loop.py` / `metrics_worker.py` / `scheduler.py`・`channels/podcast_rss.py` を足す。frontend.md の「グラフライブラリ → M2」を Recharts に直す。tech.md の依存の表に `defusedxml` と Recharts を足す
- [x] 0.3 依存を足す：backend に `defusedxml`（`uv lock`）、frontend に `recharts`（**React 19 対応の版を確かめてから**）。`docker compose up --build -V` で作り直して import できることを確認
- [x] 0.4 設定：`RUN_METRICS_WORKER`（既定 `true`）。`.env.example` とテストの conftest に追記（compose は `RUN_CONVERSION_WORKER` と同じく既定値に任せる）

## 1. データモデルとマイグレーション（S1 / S4 / S6・`design.md` §3）

- [x] 1.1 `channels/capabilities.py`：`MetricField` と `metric_fields` / `primary_metric` を足す（§4 の表）。既存のテストが通ること
- [x] 1.2 `metrics/models.py`：`MetricSnapshot` / `JobRun` / `JobRunItem` / `PodcastFeed` / `PodcastEpisode`
- [x] 1.3 マイグレーション生成 → **部分 UNIQUE 2本（定期の `(project_id, kind, target_date)`・実行中の `(project_id, kind)`）、PK、CHECK、複合 FK を目視** → `upgrade head` / `downgrade -1` / `upgrade head` が通る
- [x] 1.4 DB 制約のテスト：同じ公開物×日の二重 INSERT が IntegrityError、定期の run が同じ日に2件入らない、実行中の run が同じ企画×種類で2件入らない、負の値・他企画の公開物で IntegrityError
- [ ] 1.5 `.importlinter`：containers と service 系の契約に `metrics` を足す。新しい契約（metrics.service は `app.channels.qiita` / `app.channels.podcast_rss` / `httpx` を import しない）

## 2. 認可とスナップショット（S1 / S7・`design.md` §5・§4）

- [ ] 2.1 `Permission.METRICS_INPUT`（owner / editor）・`METRICS_COLLECT`（owner）を足す。既存の権限テストに reviewer / demo の否定を足す
- [ ] 2.2 `SnapshotService`：`record_fetched`（システム用・UPSERT）、`input_manual`（`metrics = manual` のチャネルだけ・チャネルに無い指標・未来日・公開日前・負の値を 422）、`list_for_publication`
- [ ] 2.3 ユニットテスト：同日の上書き ／auto のチャネルへの手入力で 422 ／reviewer・demo の 403 ／他企画の公開物は 404 ／取消済みの公開物のスナップショットも読める

## 3. ジョブの実行基盤（S2 / S3 / S4・`design.md` §6）

- [ ] 3.1 `jobs/loop.py`：`run_forever(run_once, interval)` を切り出し、変換ワーカー（`worker.py`）をこれに寄せる。**変換の既存テストがそのまま通ること**
- [ ] 3.2 `JobService`：`request_run`（手動・409）、`retry`（失敗 item だけで新しい run・元を書き換えない・失敗が無ければ 422）、`claim`（`SKIP LOCKED`・`next_run_at <= now()`）、`succeed` / `fail`（リトライの判定・間隔・上限・run の件数と最終状態）、`reap_stuck`（10分）
- [ ] 3.3 `jobs/scheduler.py`：`tick(now)`。JST 05:00 以降、対象の企画ごとに `ON CONFLICT DO NOTHING` で投入。実行中なら見送る
- [ ] 3.4 `jobs/metrics_worker.py`：`run_once`（拾う → DB の外で取得 → 書く）。60秒ごとに `tick`。`main.py` の lifespan で変換とは**別のタスク**として起動する
- [ ] 3.5 ユニットテスト：**同じ日に何度 tick しても run は1件** ／05:00 前は入らない ／リトライの間隔（乱数を注入）と5回で確定 ／401・404 はリトライしない ／429 は attempts を増やさず同じチャネルの残りを後ろにずらす ／止まった item の回収 ／`succeeded` / `partially_failed` / `failed`

## 4. Qiita の指標取得（S2・`design.md` §7）

- [ ] 4.1 `QiitaClient.get_item_metrics`：`GET /api/v2/items/:id`、`page_views_count` が NULL ならそのまま NULL。429 で `Rate-Reset` を `QiitaRateLimitedError.reset_at` に入れる。呼び出しの間を最低1秒あける
- [ ] 4.2 `MetricsFetcher` ポートと deps の組み立て。公開した人（`published_by`）のトークンを復号して渡す。トークンが無ければ `qiita_token_missing` で確定失敗
- [ ] 4.3 テスト（`httpx.MockTransport`）：指標の対応・NULL・401 / 404 / 429 / 5xx・タイムアウトの写し方 ／トークンがログ・エラーに出ない
- [ ] 4.4 **実機の確認（Qiita）**：自分のトークンで `page_views_count` が取れるか・限定共有の記事が取れるか・レート制限の応答ヘッダの名前を確かめ、`design.md` §7-1 と §17 を確定値に直す（publishing 6.8 と一緒に行う）
- [ ] 4.5 **ここで本番相当の環境（ローカルの常駐でよい）でワーカーを動かし始め、スナップショットを溜め始める**（M2 の判定「1週間放置」のため、なるべく早く）

## 5. ポッドキャスト RSS（S6・`design.md` §8）

- [ ] 5.1 `channels/podcast_rss.py`：SSRF の対策（https だけ・内部アドレスの拒否・リダイレクトを行き先ごとに検証・5MB・15秒・**検証した IP に直接つなぐ**）と `defusedxml` での解析。識別子は guid → enclosure → link
- [ ] 5.2 テスト：プライベート IP・ループバック・`169.254.169.254`・リダイレクト先が内部・5MB 超え・外部実体を含む XML をすべて拒否 ／RSS 2.0 の item の読み取り ／guid が無い場合
- [ ] 5.3 publishing に `PublicationService.register_episode` を足す（`CONTENT_PUBLISH` を確認 → コンテンツ作成 → 公開物 → `mark_published`）。metrics からは `PublicationGateway` 経由で呼ぶ
- [ ] 5.4 `FeedService`：登録（その場で1回取得して検証・422）・変更・削除・登録時に取り込みジョブを1件投入。ワーカーの `podcast_rss` の処理（登録した owner として認可を通し直す・`podcast_episodes` で重複と取消後の復活を止める・1エピソード1トランザクション）
- [ ] 5.5 ユニットテスト：二度登録しない ／取消した公開物が次の取り込みで復活しない ／登録した人が owner でなくなっていたら `forbidden` で確定失敗 ／editor の登録は 403
- [ ] 5.6 実機の確認：自分のポッドキャストの RSS で既存エピソードが取り込まれ、カンバンで `公開済` になる
- [ ] 5.7 【M2・任意】エピソードを既存のネタにまとめる（`design.md` §8-4）。時間が足りなければ Phase 2 として requirements に明記する

## 6. API と SSE（S4 / S5 / S7・`design.md` §10・§11）

- [ ] 6.1 ルーター：スナップショット（GET・PUT）、ジョブ（一覧・1件・手動実行・再実行）、RSS（GET / PUT / DELETE）
- [ ] 6.2 SSE：`GET .../job-runs/{run_id}/events`。最初に認可と企画の確認 → ストリームの中は1秒ごとに短いセッション → 変化したら `progress`、確定で `done`、15秒ごとに keep-alive。接続直後に現在の状態を送る
- [ ] 6.3 API 結合テスト：手動実行 → `run_once` → スナップショット。SSE は他企画の run で 404・`done` で閉じる。401 / 403 / 404 / 409 / 422。`test_openapi_lists_every_endpoint` に足す
- [ ] 6.4 `ruff` / `mypy` / `lint-imports` / `pytest` 緑。OpenAPI を書き出して `frontend/types/api.ts` を生成し直す

## 7. 分析クエリ（S8 / S9 / S10・`design.md` §9）

- [ ] 7.0 **11月中旬の判断**：この時点の実績時間を見て、削る順番の1番目（分析画面の統合）を発動するか決める。発動するなら 7.5 と 8.5 を飛ばし、requirements の【統合時に落とせる】を Phase 2 と明記する
- [ ] 7.1 `analytics.py`：直近30日（`generate_series` ＋ `lag()` の増分）・Top5（直近7日の増加量）・在庫サマリ
- [ ] 7.2 `analytics.py`：公開後 N 日の伸びカーブ（0〜90日・最大10件）
- [ ] 7.3 `analytics.py`：タグ別（公開後30日時点・`avg` と `percentile_cont(0.5)`・30日未満は対象外）・公開月コホート
- [ ] 7.4 テスト：**欠測を含む小さな既知のデータ**で、増分・Top5・伸びカーブ・タグ別の中央値・コホートの値が期待どおり ／取消した公開物が入らない ／チャネルを混ぜない
- [ ] 7.5 【統合時に落とせる】曜日別・文字数帯別（本文が空のものは対象外）とテスト
- [ ] 7.6 `AnalyticsService` とルーター（`/metrics/dashboard` / `curves` / `by-tag` / `cohorts`、統合しなければ `by-weekday` / `by-length`）。OpenAPI と型を生成し直す

## 8. 画面（`design.md` §12）

- [ ] 8.1 BFF：SSE 専用の Route Handler `app/api/streams/projects/[id]/job-runs/[runId]/route.ts`（Cookie → Bearer・`upstream.body` をそのまま返す・`X-Accel-Buffering: no`・切断で中断・セグメントの検証はパススルーと共通）。**書く前に `node_modules/next/dist/docs/` の Route Handler とストリーミングを読む**
- [ ] 8.2 `/projects/[id]/jobs`：実行履歴・失敗した item・手動実行・再実行（owner だけボタンを出す）・RSS の登録。TanStack Query ＋ `EventSource` で進捗をキャッシュに反映
- [ ] 8.3 `/projects/[id]/metrics`：ダッシュボード（チャネルのタブ・直近30日・Top5・在庫サマリ・最終取得日時と直近の失敗・空の状態）。グラフは Client Component に整形済みの配列を渡す
- [ ] 8.4 `/projects/[id]/publications/[pubId]`：推移グラフ（欠測は線をつながない・手入力の値を見分けられる）と手入力フォーム（Server Action・manual のチャネルで owner / editor のときだけ）
- [ ] 8.5 【統合時は代わりにダッシュボードへ3パネル】`/projects/[id]/metrics/analysis`：伸びカーブ（公開物の選択）・タグ別・コホート・曜日別・文字数帯別
- [ ] 8.6 導線：プロジェクト画面からダッシュボードとジョブ画面へ、公開済み一覧・コンテンツの公開物から推移へ
- [ ] 8.7 `npm run lint` / `npx next typegen` / `npx tsc --noEmit` / `npm run build` 緑

## 9. 仕上げ

- [ ] 9.1 手動確認（M2 の判定）：**Qiita の公開物があり RSS を登録した企画で、1週間放置してスナップショットが溜まっている。** 手動実行で進捗が流れる。ワーカーを止めて 05:00 を過ぎてから起動すると今日の分が入る
- [ ] 9.2 README に、指標取得の仕組み（定期実行の時刻・リトライ・失敗したときの見方と再実行）と `RUN_METRICS_WORKER` を書く。CLAUDE.md のコマンドが増えていれば追記
- [ ] 9.3 `requirements.md` の M2 の受け入れ条件にチェックを入れ、テストとの対応を `acceptance-trace.md` に残す
- [ ] 9.4 steering / `requirements-overview.md`（§8 のデータモデルの `ingest_jobs / job_runs` を実際の名前に・§13）を更新
- [ ] 9.5 `/code-review` を実施し、指摘を修正

## 10. 性能の実測（M3・S11・`design.md` §15-1）

- [ ] 10.1 `python -m app.cli seed-metrics --rows 500000`（本番の環境では拒否する）
- [ ] 10.2 ダッシュボードと分析の各 SQL を `EXPLAIN (ANALYZE, BUFFERS)` で測る。インデックスの有無で Before/After をとる
- [ ] 10.3 目標（ダッシュボード 1秒・分析 2秒）を外したら、月次のマテリアライズドビューを足して測り直し、ADR-0008 に追記する
- [ ] 10.4 README に Before/After を載せる

---

## 完了の定義

- `requirements.md` の **M2** の受け入れ条件をすべて満たす（M3 の条件と、統合で落とした条件は理由を書いて残す）
- `/code-review` を実施し、`requirements.md` との整合を確認する（`CLAUDE.md`「実装検証」）
- **1週間ぶんのスナップショットが実際に溜まっていて、ダッシュボードで推移が見える**
