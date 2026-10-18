# ADR-0017: M1 の変換ジョブを DB キューで回す

- **日付**: 2026-10-18
- **ステータス**: 採用
- **関連**: ADR-0013（ジョブ基盤・検討中）、`.kiro/specs/publishing/design.md` §7

## 背景

publishing の M1 で、本文を Claude API で Qiita 体裁に変換する（数十秒〜数分）。
requirements は「リクエストを待たせず実行し、状態を画面に出す」を求めている。

一方、ジョブ基盤（ADR-0013）は M2 着手前に決めることにしていて、M1 の時点では無い。
**基盤なしで非同期にし、M2 で基盤に載せ替えられる形**が要る。

## 選択肢

| 案 | 利点 | 欠点 |
|---|---|---|
| **FastAPI の BackgroundTasks** | 追加の仕組みが要らない | このアプリの commit はレスポンス送信後に `get_session` の後片付けで走る（foundation §4-4）。BackgroundTasks もレスポンス送信後に動くので、**ジョブの行が commit される前に処理が始まりうる**。順番が FastAPI 内部の実装頼み。プロセスが落ちるとジョブが消え、拾い直せない |
| **`asyncio.create_task` をハンドラから直接** | 同上 | BackgroundTasks と同じ問題に加え、タスクの参照管理・終了処理を自前で持つ |
| **ADR-0013 の基盤を前倒しで決める** | M2 で載せ替えが要らない | Redis の追加、基盤の選定を M1 の 22h に詰めることになる。選定は指標取得ジョブ（M2）の要件で決めたい |
| **DB をキューにした常駐ワーカー** | 行が commit されてから拾うので順番の問題が無い。落ちても行が残り拾い直せる。追加のミドルウェア不要 | ポーリングの遅延（2秒）。止まったジョブの回収を自前で持つ |

## 決定

**`conversion_jobs` の行をキューにし、同じプロセスの常駐ワーカー（lifespan で起動する asyncio タスク）が拾う。**

- 拾うときは `SELECT ... WHERE status = 'queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED` → `running` にして commit
- Claude の呼び出しは **DB の接続もロックも持たずに**行い、終わったら別のセッションで結果を書く
- `running` のまま 15分を超えた行は `failed`（`interrupted`）に回収する。Claude 呼び出しのタイムアウト（10分）より長くとる
- commit の持ち主はワーカー（cli.py と同じく Service の外）。Service は flush だけ
- 設定 `RUN_CONVERSION_WORKER`（既定 `true`）。テストでは `false` にし、ワーカーの関数を直接呼ぶ

## 理由

- **commit の順番に依存しない。** API は行を INSERT して 202 を返すだけで、ワーカーは commit 済みの行しか見えない
- **`SKIP LOCKED` で複数ワーカーでも同じ行を拾わない。** `uvicorn --workers` を増やしても、将来ワーカーを別コンテナに出しても、そのまま動く
- **行が状態を持つので、落ちても失われない。** 画面はこの行の状態を取り直すだけで進捗を出せる
- BackgroundTasks を却下したのは、上の順番の問題とプロセス停止での消失。基盤の前倒しを却下したのは、M1 の工数と、選定の主軸（指標取得のリトライ・スケジュール）が M2 にあるため

## 影響

- **M2 で ADR-0013 の基盤を入れるとき、書き直すのは `app/jobs/worker.py` だけにする。** そのために M1 で `JobDispatcher` ポートを切っておく（M1 は何もしない実装。M2 で「キューに id を積む」実装に替える）。`ConversionService` の `request / claim / complete / fail` と画面は変えない
- `conversion_jobs` は M2 の `job_runs` と役割が重なる。M2 で `job_runs` を設計するときに、統合するか変換専用のまま残すかを決める
- ポーリングのため、変換の開始は最大2秒遅れる。変換自体が数十秒かかるので問題にしない
