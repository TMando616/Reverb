# tasks.md — publishing（チャネル変換・公開）

> **前提**：`requirements.md`（`cd2ee16`）・`design.md`（`e1a4315`）は承認済み。
> **範囲**：**M1（約 22h）だけ。** C7（intent / manual・貼り戻し）・C9（タグ提案）・プロファイルの編集画面・X / note / podcast は M3 で着手するときにここへ足す。
> **進め方**：content-pipeline と同じく「縦に1本通す」。**バックエンドを機能ごとに通してから画面**（トークン → 変換 → 原稿 → 投稿 → 取消 → 画面）。
> Service / Repository のユニットテストを併走させる（`design.md` §15）。
> **1サブタスク完了ごとにコミット**し、ユーザーにプッシュを促す。

## 0. 実装前の整備（`design.md` §17「このスペックで新たに決めたこと」）

- [x] 0.1 ADR-0017「M1 の変換ジョブを DB キューで回す」を書く（BackgroundTasks を使わない理由・`SKIP LOCKED`・止まったジョブの回収・`JobDispatcher` で M2 に載せ替える境界）。ADR-0013 から参照し、`docs/adr/README.md` の索引に足す
- [x] 0.2 steering：structure.md に `app/llm/` を足す（`channels/` との違い）。tech.md の依存の表に `anthropic` / `cryptography` を足す
- [x] 0.3 `requirements-overview.md` §8 のデータモデルから `channels` テーブルを外し、チャネルはコードに置くことを書く。`contents/service.py` の `ALLOWED` のコメントを「`published` は公開操作の中だけ」に直す
- [x] 0.4 依存を足す：`anthropic`・`cryptography`、`httpx` を dev から本体へ。`uv lock` → コンテナを作り直して import できることを確認
- [ ] 0.5 設定：`TOKEN_ENCRYPTION_KEYS` / `CONVERSION_MODEL` / `CONVERSION_EFFORT` / `RUN_CONVERSION_WORKER`。`ENVIRONMENT=production` で鍵が空なら起動時に落とす。`.env.example` と compose に追記（`ANTHROPIC_API_KEY` は SDK に解決させる）

## 1. データモデルとマイグレーション（C2 / C3 / C4 / C5 / C8）

- [ ] 1.1 `channels/capabilities.py`：`ChannelCode`（StrEnum）と `CAPABILITIES`（ADR-0005 の項目。M1 で `publish == "auto"` は Qiita だけ）
- [ ] 1.2 `publishing/models.py`：`ConversionProfile` / `ConversionJob` / `ChannelDraft` / `ChannelAccount` / `Publication`。チャネルは `text` ＋ CHECK、`ChannelDraft.version` は `version_id_col`（`design.md` §3）
- [ ] 1.3 マイグレーション生成 → **部分 UNIQUE 3本（jobs の待機・実行中 / publications の未取消×2）と複合 FK を目視** → `upgrade head` / `downgrade -1` / `upgrade head` が通る
- [ ] 1.4 DB 制約のテスト：待機中ジョブの二重 INSERT と未取消公開物の二重 INSERT が IntegrityError、取消済みなら同じ組でも入る、他企画のコンテンツを参照すると IntegrityError
- [ ] 1.5 `.importlinter`：containers と service 系の契約に `publishing` を足す。新しい契約2本（publishing.service は `app.channels` / `app.llm` / `anthropic` / `httpx` を import しない、`app.jobs` は `*.repository` を import しない）

## 2. 認可・状態遷移の変更（C8 / `design.md` §4・§5）

- [ ] 2.1 `Permission.CONTENT_PUBLISH` を足す（owner のみ・demo は落ちる）。既存の権限テストに editor / reviewer / demo の否定を足す
- [ ] 2.2 `ContentService.lock_for_publish`（`SELECT ... FOR UPDATE`）/ `mark_published`（`PUBLISHABLE_FROM` 以外は 422・`published → published` はログなし）/ `mark_unpublished`（`published → drafting`・遷移ログ）
- [ ] 2.3 ユニットテスト：汎用の遷移 API で `to=published` が 422 のまま ／`受信箱` から `mark_published` で 422 ／`mark_unpublished` でログが1件

## 3. Qiita トークン（C5）

- [ ] 3.1 `core/crypto.py`：`TokenCipher`（`MultiFernet`・先頭の鍵で暗号化・古い鍵の暗号文を検出して暗号化し直せる）。`TokenUnavailableError` のメッセージに値を含めない
- [ ] 3.2 `channels/qiita.py`：`QiitaClient`（`httpx.AsyncClient`・15秒・再試行なし）の `authenticated_user` / `create_item` / `update_item`。ステータス → 例外の対応（`design.md` §10-5）
- [ ] 3.3 `AccountService`（`get` / `register` / `delete`・常に `actor.user_id`・demo 403）と `ChannelAccountRepository`。登録時に `authenticated_user` で確かめ、401 / 403 は 422 `invalid_qiita_token`
- [ ] 3.4 ルーター：`GET/PUT/DELETE /me/accounts/qiita`（トークンを返さない）。`core/exceptions.py` に publishing のエラーコードを足し、ハンドラに登録（`design.md` §12）
- [ ] 3.5 ユニットテスト：暗号の往復 ／鍵の差し替え ／改ざんで失敗 ／`QiitaClient` を `httpx.MockTransport` でステータスごと・POST を再試行しない ／登録・差し替え・削除 ／demo 403 ／**`caplog` にトークンが出ない**

## 4. 変換（C2 / C3）

- [ ] 4.1 `service.py` にポートを置く：`Converter` / `ConversionInput` / `ConversionOutput` / `ConversionFailed`、`JobDispatcher`（M1 は何もしない実装）、`ContentGateway`
- [ ] 4.2 `llm/prompts.py`：Qiita の `DEFAULT_PROFILES`（グローバル CLAUDE.md §5 の Qiita の節を移植・禁則フレーズは配列）と system / user の組み立て（`design.md` §8-2）
- [ ] 4.3 **`/claude-api` スキルを読み直してから** `llm/converter.py`：`AsyncAnthropic`・`messages.stream` ＋ `get_final_message`・effort medium・structured outputs `{title, body, tags}`・`max_tokens` 64000・timeout 600秒・`fallbacks: "default"`。例外と `stop_reason` を `error_code` に（§8-3）。`usage` と `request_id` を返す
- [ ] 4.4 `ConversionService.request`（WRITE・プロファイルが無ければ既定値から作る・`profile_snapshot` と `source_revision_no` を写す・部分 UNIQUE 違反は 409 `conversion_in_progress`）
- [ ] 4.5 `ConversionService.claim`（`FOR UPDATE SKIP LOCKED`）/ `complete` / `fail` / `reap_stuck`（15分以上 `running` → `interrupted`）。`complete` で原稿へ反映（§9-2 の3分岐）
- [ ] 4.6 `jobs/worker.py`：2秒のループ（回収 → 拾う → DB の外で変換 → 書く）。commit はワーカーが持つ。`main.py` の lifespan で起動・停止、`RUN_CONVERSION_WORKER=false` で起動しない
- [ ] 4.7 ルーター：`GET /channels`、`POST .../channels/{ch}/conversions`（202）、`GET .../conversions`、`GET .../conversions/{job_id}`
- [ ] 4.8 ユニットテスト：editor は変換できる・reviewer / demo 403 ／二重実行 409 ／2つ目の `claim` は同じ行を拾わない ／回収 ／`FakeConverter` の各失敗が `error_code` になる ／`converter.py` を SDK のクライアント差し替えで（refusal / max_tokens / Schema 不一致 / 各例外）

## 5. チャネル原稿（C4）

- [ ] 5.1 `DraftService.save`（WRITE・`expected_version`・`edited_after_apply = true`・`extra` を Pydantic で検証）/ `apply`（`pending_job_id` の結果で置き換え・409）
- [ ] 5.2 `GET .../channels/{ch}`：原稿・最新ジョブ・保留中ジョブの結果・未取消の公開物・最新リビジョン番号をまとめて返す
- [ ] 5.3 ルーター：`PUT .../draft`、`POST .../draft/apply`
- [ ] 5.4 ユニットテスト：§9-2 の3分岐（無い → 作る／手直しなし → 置き換え／手直しあり → 保留）／apply の 409 ／原稿が古いことの判定（`source_revision_no`、状態遷移だけでは古くならない）

## 6. Qiita への投稿・更新・取消（C6 / C8）

- [ ] 6.1 `PublicationService.publish_qiita`（`design.md` §10-3 の9段・Qiita の制約の検証 §10-4・送信直後と記録失敗時のログ）
- [ ] 6.2 `PublicationService.push_qiita`（公開物が無ければ 404・`last_pushed_at`・限定共有 → 一般公開だけ許す）
- [ ] 6.3 `PublicationService.cancel`（論理削除・未取消が0件なら `mark_unpublished`）と企画の公開済み一覧
- [ ] 6.4 ルーター：`POST .../channels/qiita/publish`、`POST .../channels/qiita/push`、`DELETE /projects/{id}/publications/{pub_id}`、`GET /projects/{id}/publications`
- [ ] 6.5 ユニットテスト：editor 403 ／トークンなし 409 ／タグ0個・6個で 422 ／投稿 → 公開物 → `公開済` ／2回目の投稿 409 ／Qiita の各エラーの対応 ／更新で状態が変わらない ／取消 → `drafting`・Qiita は呼ばない ／2チャネル目がある場合は取消しても `公開済` のまま（テスト用に公開物を直接作る）
- [ ] 6.6 API 結合テスト：変換 → ワーカーを1回回す → 原稿 → 編集 → 投稿 → 更新 → 取消。401 / 403 / 404 / 409 / 422。`test_openapi_lists_every_endpoint` に足す
- [ ] 6.7 `ruff` / `mypy` / `lint-imports` / `pytest` 緑。OpenAPI を書き出して `frontend/types/api.ts` を生成し直す
- [ ] 6.8 **実機の確認（Qiita・限定共有）**：実際のトークンで投稿・更新して、タグ数の上限・タイトルの上限・一般公開 → 限定共有の可否を確かめ、`design.md` §10-4 を確定値に直す。確かめた記事は手で消す

## 7. 画面（`design.md` §13）

- [ ] 7.1 BFF：`/channels` と `/me/accounts/...` のパススルーを足す
- [ ] 7.2 `/settings/accounts`：Qiita トークンの登録・差し替え・削除（Server Component ＋ Server Action・`write_qiita` スコープの案内・登録済みならユーザー名だけ出す）
- [ ] 7.3 `/projects/[id]/contents/[cid]/publish`：Server Component で取得 → TanStack Query に渡す。チャネルのタブ（M1 は Qiita だけ）
- [ ] 7.4 変換：実行ボタンと送信先の明示 ／`queued` / `running` のあいだだけ `refetchInterval: 2000` ／失敗の文言（§8-3）と［再実行］
- [ ] 7.5 原稿：タイトル・本文（CodeMirror を再利用）・タグ（1〜5個）・プレビュー（既存部品）。手動保存＋⌘S・409 の扱い ／「新しい変換結果があります」→ 結果のプレビュー ＋［この結果で置き換える］／「変換後に本文が更新されています」
- [ ] 7.6 投稿・更新：確認ダイアログ（既定は限定共有・一般公開の注意）／未保存なら先に保存 ／成功で URL ／トークンの問題なら設定画面へのリンク ／owner 以外にはボタンを出さない
- [ ] 7.7 公開物と取消（「Qiita 上の記事は残ります」）。`/projects/[id]/publications`（コンテンツごと・新しい順）
- [ ] 7.8 編集画面のヘッダに［公開へ］と公開物のチャネルのバッジ。プロジェクト画面から公開済み一覧への導線
- [ ] 7.9 `npm run lint` / `npx next typegen` / `npx tsc --noEmit` / `npm run build` 緑

## 8. 仕上げ

- [ ] 8.1 手動確認（M1 の判定）：**ネタ → 執筆 → Qiita 向けに変換 → 原稿を直す → 限定共有で投稿 → 一般公開に更新**が通り、カンバンで `公開済` になる。再変換で手直しが消えない。2タブで同時に投稿して1件しかできない
- [ ] 8.2 README に「Qiita に投稿できたのに記録が無いとき」の手順（`design.md` §10-3）と、`TOKEN_ENCRYPTION_KEYS` の作り方・差し替え方を書く。CLAUDE.md のコマンドが増えていれば追記
- [ ] 8.3 `requirements.md` の M1 の受け入れ条件にチェックを入れ、テストとの対応を `acceptance-trace.md` に残す
- [ ] 8.4 steering / `requirements-overview.md` §13 を更新
- [ ] 8.5 `/code-review` を実施し、指摘を修正

---

## 完了の定義

- `requirements.md` の **M1** の受け入れ条件をすべて満たす（M3 の条件は未チェックのまま残す）
- `/code-review` を実施し、`requirements.md` との整合を確認する（`CLAUDE.md`「実装検証」）
- **`metrics` が「`cancelled_at IS NULL` の公開物を日次で取りに行く」ところから始められる状態になっている**
