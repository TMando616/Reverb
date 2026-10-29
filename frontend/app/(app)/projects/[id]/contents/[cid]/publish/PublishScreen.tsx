"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { MarkdownPreview } from "@/components/contents/MarkdownPreview";
import { Dialog } from "@/components/ui/Dialog";
import { bffFetch } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import {
  STATUS_LABELS,
  VISIBILITY_LABELS,
  formatDateTime,
  type ChannelDraft,
  type ChannelView,
  type ContentStatus,
  type ConversionJob,
  type JobStatus,
  type Publication,
  type Visibility,
} from "@/lib/api/types";

import { MarkdownEditor } from "../MarkdownEditor";
import { useLeaveGuard } from "../use-leave-guard";
import { TOKEN_ERRORS, conversionError, requestError } from "./messages";
import { parseTags, useChannelDraft } from "./use-channel-draft";

const CHANNEL = "qiita";
/** 変換が終わるまで取り直す間隔（design.md §13-3）。M2 で SSE に置き換える。 */
const POLL_MS = 2_000;

const JOB_TEXT: Record<JobStatus, string> = {
  queued: "変換待ち…",
  running: "変換中…（数十秒〜数分かかります）",
  succeeded: "変換済み",
  failed: "変換に失敗",
};

const isActive = (job: ConversionJob | null | undefined) =>
  job?.status === "queued" || job?.status === "running";

type Props = {
  projectId: number;
  contentId: number;
  title: string;
  status: ContentStatus;
  initial: ChannelView;
  canWrite: boolean;
  canPublish: boolean;
  qiitaRegistered: boolean;
};

type Notice = { text: string; tokenLink?: boolean } | null;

/**
 * 公開画面（publishing design.md §13）。M1 のチャネルは Qiita だけ。
 * サーバー状態（原稿・ジョブ・公開物）は TanStack Query、原稿の編集中バッファはローカル状態。
 */
export function PublishScreen(props: Props) {
  const { projectId, contentId, canWrite, canPublish } = props;
  const router = useRouter();
  const queryClient = useQueryClient();
  const key = queryKeys.channel(projectId, contentId, CHANNEL);
  const base = `/projects/${projectId}/contents/${contentId}`;

  const { data: view = props.initial } = useQuery({
    queryKey: key,
    queryFn: async () => {
      const result = await bffFetch<ChannelView>(`${base}/channels/${CHANNEL}`);
      if (!result.ok) throw new Error(result.message);
      return result.data;
    },
    // 変換が待機中・実行中のあいだだけ取り直す。終わったら止まる。
    refetchInterval: (query) => (isActive(query.state.data?.latest_job) ? POLL_MS : false),
  });

  const writer = useChannelDraft(projectId, contentId, CHANNEL, view.draft ?? null);
  const { buffer, setBuffer, dirty } = writer;
  useLeaveGuard(dirty || writer.saving);

  const [notice, setNotice] = useState<Notice>(null);
  const [mode, setMode] = useState<"edit" | "preview">("edit");
  const [busy, setBusy] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);

  // 変換が失敗で終わった瞬間に、理由を通知欄にも出す（描画中に前回の状態と比べる）。
  const jobStatus = view.latest_job?.status;
  const [lastStatus, setLastStatus] = useState(jobStatus);
  if (jobStatus !== lastStatus) {
    setLastStatus(jobStatus);
    if ((lastStatus === "queued" || lastStatus === "running") && jobStatus === "failed") {
      setNotice({ text: conversionError(view.latest_job?.error_code) });
    }
  }

  const { save } = writer;
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save().then((r) => setNotice(r.ok ? null : { text: r.message }));
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [save]);

  function fail(status: number, code: string, message: string) {
    setNotice({ text: requestError(status, code, message), tokenLink: TOKEN_ERRORS.has(code) });
  }

  async function convert() {
    setBusy(true);
    const result = await bffFetch<ConversionJob>(`${base}/channels/${CHANNEL}/conversions`, {
      method: "POST",
    });
    setBusy(false);
    if (!result.ok) return fail(result.status, result.code, result.message);
    setNotice(null);
    queryClient.setQueryData<ChannelView>(key, (v) => (v ? { ...v, latest_job: result.data } : v));
  }

  async function applyPending(job: ConversionJob) {
    if (
      dirty &&
      !window.confirm("未保存の変更を捨てて、新しい変換結果で置き換えます。よろしいですか？")
    ) {
      return;
    }
    setBusy(true);
    const result = await bffFetch<ChannelDraft>(`${base}/channels/${CHANNEL}/draft/apply`, {
      method: "POST",
      body: JSON.stringify({ job_id: job.id, expected_version: writer.baseVersion }),
    });
    setBusy(false);
    if (!result.ok) return fail(result.status, result.code, result.message);
    writer.adopt(result.data);
    setNotice(null);
    await queryClient.invalidateQueries({ queryKey: key });
  }

  /** 投稿・更新の前に、未保存の原稿を保存する。保存に失敗したら送らない。 */
  async function saveBeforeSending(): Promise<number | null> {
    if (!dirty) return writer.baseVersion;
    const result = await save();
    if (!result.ok) {
      setNotice({ text: result.message });
      return null;
    }
    return result.version;
  }

  async function publish(visibility: Visibility) {
    setBusy(true);
    const version = await saveBeforeSending();
    if (version === null) return setBusy(false);
    const result = await bffFetch<Publication>(`${base}/channels/${CHANNEL}/publish`, {
      method: "POST",
      body: JSON.stringify({ visibility, expected_draft_version: version }),
    });
    setBusy(false);
    setPublishOpen(false);
    if (!result.ok) return fail(result.status, result.code, result.message);
    setNotice({ text: `Qiita に投稿しました：${result.data.url}` });
    await queryClient.invalidateQueries({ queryKey: key });
    router.refresh(); // 状態（公開済）を取り直す
  }

  async function push(visibility?: Visibility) {
    if (
      visibility === "public" &&
      !window.confirm("一般公開にします。一般公開から限定共有には戻せません。")
    ) {
      return;
    }
    setBusy(true);
    const version = await saveBeforeSending();
    if (version === null) return setBusy(false);
    const result = await bffFetch<Publication>(`${base}/channels/${CHANNEL}/push`, {
      method: "POST",
      body: JSON.stringify({ expected_draft_version: version, visibility }),
    });
    setBusy(false);
    if (!result.ok) return fail(result.status, result.code, result.message);
    setNotice({ text: "Qiita の記事を更新しました" });
    await queryClient.invalidateQueries({ queryKey: key });
  }

  async function cancel(publication: Publication) {
    if (
      !window.confirm(
        "公開を取り消します。Reverb 上の記録が取消になり、Qiita 上の記事は残ります（必要なら Qiita で消してください）。",
      )
    ) {
      return;
    }
    setBusy(true);
    const result = await bffFetch<void>(`/projects/${projectId}/publications/${publication.id}`, {
      method: "DELETE",
    });
    setBusy(false);
    if (!result.ok) return fail(result.status, result.code, result.message);
    setNotice({ text: "公開を取り消しました。Qiita 上の記事は残っています" });
    await queryClient.invalidateQueries({ queryKey: key });
    router.refresh();
  }

  const job = view.latest_job;
  const pending = view.pending_job;
  const publication = view.publication;
  const tagCount = buffer ? parseTags(buffer.tags).length : 0;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div className="flex flex-col gap-1">
          <Link
            href={`/projects/${projectId}/contents/${contentId}`}
            className="text-sm text-gray-500 hover:underline"
          >
            ← 編集画面
          </Link>
          <h1 className="text-xl font-bold">{props.title}</h1>
        </div>
        <span className="rounded bg-gray-100 px-2 py-0.5 text-sm text-gray-700">
          {STATUS_LABELS[props.status]}
        </span>
      </div>

      <div role="tablist" aria-label="チャネル" className="flex gap-1 border-b border-gray-200">
        <span
          role="tab"
          aria-selected
          className="border-b-2 border-gray-900 px-3 py-1 text-sm font-bold"
        >
          Qiita
        </span>
      </div>

      {notice && (
        <p aria-live="polite" className="text-sm text-gray-800">
          {notice.text}
          {notice.tokenLink && (
            <>
              {" "}
              <Link href="/settings/accounts" className="underline">
                トークンの設定へ
              </Link>
            </>
          )}
        </p>
      )}

      {/* 変換 */}
      <section className="flex flex-col gap-2 rounded border border-gray-200 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-bold">Qiita 向けに変換</h2>
          {canWrite && (
            <button
              type="button"
              onClick={() => void convert()}
              disabled={busy || isActive(job)}
              className="rounded bg-gray-900 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              {job ? "もう一度変換する" : "変換する"}
            </button>
          )}
        </div>
        {canWrite && (
          <p className="text-xs text-gray-500">
            本文を Claude
            API（Anthropic）に送って変換します。変換プロファイル（構成・語尾・一人称・使わない表現）に沿って書き直します。
          </p>
        )}
        {job && (
          <p
            className={`text-sm ${job.status === "failed" ? "text-red-600" : "text-gray-700"}`}
            aria-live="polite"
          >
            {JOB_TEXT[job.status]}
            {job.status === "failed" && `：${conversionError(job.error_code)}`}
            {job.finished_at && `（${formatDateTime(job.finished_at)}）`}
          </p>
        )}
      </section>

      {/* 原稿 */}
      {buffer === null ? (
        <p className="text-sm text-gray-600">
          まだ原稿がありません。{canWrite ? "「変換する」から作れます。" : ""}
        </p>
      ) : (
        <section className="flex flex-col gap-3">
          {pending && (
            <div className="flex flex-col gap-2 rounded border border-blue-300 bg-blue-50 p-3 text-sm">
              <p>
                新しい変換結果があります。原稿を手で直していたので、置き換えずに保留しています。
              </p>
              <details>
                <summary className="cursor-pointer">変換結果を見る</summary>
                <div className="mt-2 rounded border border-blue-200 bg-white p-3">
                  <p className="font-bold">{pending.result_title}</p>
                  <p className="text-xs text-gray-500">タグ：{pending.result_tags.join(", ")}</p>
                  <MarkdownPreview markdown={pending.result_body ?? ""} />
                </div>
              </details>
              {canWrite && (
                <button
                  type="button"
                  onClick={() => void applyPending(pending)}
                  disabled={busy}
                  className="self-start rounded border border-blue-400 bg-white px-2 py-1"
                >
                  この結果で置き換える
                </button>
              )}
            </div>
          )}
          {view.draft_is_stale && (
            <p className="rounded border border-amber-300 bg-amber-50 p-2 text-sm text-amber-900">
              変換したあとに本文が更新されています。必要ならもう一度変換してください（投稿はこのままでもできます）。
            </p>
          )}
          {writer.conflict && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded border border-red-300 bg-red-50 p-2 text-sm text-red-900"
            >
              <span>原稿が他の画面で更新されました。</span>
              <button
                type="button"
                onClick={() => void writer.reload()}
                className="rounded border border-red-300 bg-white px-2 py-0.5"
              >
                最新を読み込む（自分の編集は破棄）
              </button>
            </div>
          )}

          <input
            value={buffer.title}
            onChange={(e) => setBuffer((b) => (b ? { ...b, title: e.target.value } : b))}
            readOnly={!canWrite}
            maxLength={255}
            aria-label="タイトル"
            className="rounded border border-gray-300 px-3 py-2 text-lg font-bold"
          />
          <div className="flex flex-col gap-1">
            <input
              value={buffer.tags}
              onChange={(e) => setBuffer((b) => (b ? { ...b, tags: e.target.value } : b))}
              readOnly={!canWrite}
              aria-label="タグ"
              placeholder="Python, FastAPI"
              className="rounded border border-gray-300 px-2 py-1 text-sm"
            />
            <span
              className={`text-xs ${tagCount < 1 || tagCount > 5 ? "text-red-600" : "text-gray-500"}`}
            >
              タグはカンマ区切りで1〜5個（今 {tagCount} 個）
            </span>
          </div>

          <div
            role="group"
            aria-label="表示"
            className="flex self-start overflow-hidden rounded border border-gray-300 text-sm"
          >
            {(
              [
                ["edit", "編集"],
                ["preview", "プレビュー"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
                className={`px-2 py-1 ${mode === value ? "bg-gray-900 text-white" : ""}`}
              >
                {label}
              </button>
            ))}
          </div>
          {mode === "edit" && canWrite ? (
            <MarkdownEditor
              value={buffer.body}
              onChange={(body) => setBuffer((b) => (b ? { ...b, body } : b))}
            />
          ) : (
            <div className="min-h-[40vh] rounded border border-gray-200 bg-white p-4 text-gray-900">
              <MarkdownPreview markdown={buffer.body} />
            </div>
          )}

          {canWrite && (
            <div className="flex items-center gap-2 text-sm">
              <button
                type="button"
                onClick={() =>
                  void save().then((r) => setNotice(r.ok ? null : { text: r.message }))
                }
                disabled={!dirty || writer.saving}
                className="rounded border border-gray-300 px-3 py-1 disabled:opacity-50"
              >
                {writer.saving ? "保存中…" : "原稿を保存（⌘S）"}
              </button>
              <span className={dirty ? "text-amber-700" : "text-gray-500"}>
                {dirty ? "未保存の変更あり" : "保存済み"}
              </span>
            </div>
          )}
        </section>
      )}

      {/* 公開 */}
      <section className="flex flex-col gap-2 rounded border border-gray-200 p-3">
        <h2 className="font-bold">Qiita への公開</h2>
        {publication ? (
          <div className="flex flex-col gap-2 text-sm">
            <p>
              <a href={publication.url} target="_blank" rel="noreferrer" className="underline">
                {publication.url}
              </a>
              <span className="ml-2 rounded bg-gray-100 px-1.5 text-xs">
                {publication.visibility ? VISIBILITY_LABELS[publication.visibility] : ""}
              </span>
            </p>
            <p className="text-xs text-gray-500">
              投稿 {formatDateTime(publication.published_at)}
              {publication.last_pushed_at &&
                ` ・ 最終更新 ${formatDateTime(publication.last_pushed_at)}`}
            </p>
            {canPublish && (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => void push()}
                  disabled={busy || buffer === null}
                  className="rounded bg-gray-900 px-3 py-1 text-white disabled:opacity-50"
                >
                  原稿で Qiita の記事を更新
                </button>
                {publication.visibility === "private" && (
                  <button
                    type="button"
                    onClick={() => void push("public")}
                    disabled={busy || buffer === null}
                    className="rounded border border-gray-300 px-3 py-1 disabled:opacity-50"
                  >
                    一般公開にして更新
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void cancel(publication)}
                  disabled={busy}
                  className="rounded border border-red-300 px-3 py-1 text-red-700 disabled:opacity-50"
                >
                  公開取消
                </button>
              </div>
            )}
          </div>
        ) : canPublish ? (
          <div className="flex flex-col gap-1 text-sm">
            {!props.qiitaRegistered && (
              <p className="text-gray-600">
                Qiita のトークンが未登録です。
                <Link href="/settings/accounts" className="underline">
                  トークンの設定へ
                </Link>
              </p>
            )}
            <button
              type="button"
              onClick={() => setPublishOpen(true)}
              disabled={busy || buffer === null}
              className="self-start rounded bg-gray-900 px-3 py-1 text-white disabled:opacity-50"
            >
              Qiita に投稿
            </button>
          </div>
        ) : (
          <p className="text-sm text-gray-600">
            まだ公開されていません。公開できるのは企画のオーナーです。
          </p>
        )}
      </section>

      <PublishDialog
        open={publishOpen}
        onOpenChange={setPublishOpen}
        busy={busy}
        dirty={dirty}
        onPublish={publish}
      />
    </div>
  );
}

function PublishDialog(props: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  dirty: boolean;
  onPublish: (visibility: Visibility) => Promise<void>;
}) {
  // 既定は限定共有（design.md §13-4）。開くたびに戻す。
  const [visibility, setVisibility] = useState<Visibility>("private");
  return (
    <Dialog
      open={props.open}
      onOpenChange={(open) => {
        if (open) setVisibility("private");
        props.onOpenChange(open);
      }}
      title="Qiita に投稿"
    >
      <fieldset className="flex flex-col gap-2 text-sm">
        <legend className="mb-1 text-gray-700">公開範囲</legend>
        {(["private", "public"] as const).map((value) => (
          <label key={value} className="flex items-center gap-2">
            <input
              type="radio"
              name="visibility"
              value={value}
              checked={visibility === value}
              onChange={() => setVisibility(value)}
            />
            {VISIBILITY_LABELS[value]}
            {value === "private" && (
              <span className="text-xs text-gray-500">
                （URL を知っている人だけ。あとで一般公開にできます）
              </span>
            )}
          </label>
        ))}
        {visibility === "public" && (
          <p className="text-xs text-red-700">一般公開は、あとから限定共有に戻せません。</p>
        )}
        {props.dirty && (
          <p className="text-xs text-gray-600">未保存の原稿を保存してから投稿します。</p>
        )}
      </fieldset>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={() => props.onOpenChange(false)}
          className="rounded border border-gray-300 px-3 py-1 text-sm"
        >
          やめる
        </button>
        <button
          type="button"
          onClick={() => void props.onPublish(visibility)}
          disabled={props.busy}
          className="rounded bg-gray-900 px-3 py-1 text-sm text-white disabled:opacity-50"
        >
          {props.busy ? "投稿中…" : "投稿する"}
        </button>
      </div>
    </Dialog>
  );
}
