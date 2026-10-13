"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent } from "react";

import { countChars, CHAR_COUNT_NOTE } from "@/components/contents/char-count";
import { MarkdownPreview } from "@/components/contents/MarkdownPreview";
import { CheckboxPicker } from "@/components/ui/CheckboxPicker";
import { Menu } from "@/components/ui/Menu";
import { bffFetch } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import {
  ALLOWED_TRANSITIONS,
  STATUS_LABELS,
  formatDateTime,
  type Content,
  type Tag,
} from "@/lib/api/types";

import { createTag } from "../../actions";
import { MarkdownEditor } from "./MarkdownEditor";
import { RevisionPanel } from "./RevisionPanel";
import { useContentWriter, type SaveStatus } from "./use-content-writer";
import { useLeaveGuard } from "./use-leave-guard";

type View = "edit" | "split" | "preview";

type Props = {
  projectId: number;
  initial: Content;
  tags: Tag[];
  memberNames: Record<number, string>;
};

const STATUS_TEXT: Record<SaveStatus, string> = {
  saved: "保存済み",
  dirty: "未保存の変更あり",
  saving: "保存中…",
  error: "保存失敗",
  conflict: "競合",
};

/**
 * 編集画面（content-pipeline design.md §9-5）。
 * サーバー状態（コンテンツ）は TanStack Query のキャッシュ、編集中バッファは
 * `useContentWriter` のローカル状態。この2つを混ぜない（frontend.md §2）。
 */
export function ContentEditor({ projectId, initial, tags, memberNames }: Props) {
  const { data: content = initial } = useQuery({
    queryKey: queryKeys.content(projectId, initial.id),
    queryFn: async () => {
      const result = await bffFetch<Content>(`/projects/${projectId}/contents/${initial.id}`);
      if (!result.ok) throw new Error(result.message);
      return result.data;
    },
  });
  const writer = useContentWriter(projectId, initial);
  const { draft, setDraft, status } = writer;
  useLeaveGuard(writer.dirty || status === "saving");

  const [view, setView] = useState<View>("split");
  const [showHistory, setShowHistory] = useState(false);
  const [notice, setNotice] = useState("");
  const [createdTags, setCreatedTags] = useState<Tag[]>([]);
  const [notePath, setNotePath] = useState(content.source_note_path ?? "");
  // 最後に送った値。Enter のあとの blur で同じ値をもう一度送らない
  const submittedNotePath = useRef(content.source_note_path);

  // Cmd/Ctrl + S で今すぐ保存（design.md §9-6）。
  const { saveNow } = writer;
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void saveNow();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [saveNow]);

  const allTags = [...tags, ...createdTags.filter((c) => !tags.some((t) => t.id === c.id))];
  const tagOptions = allTags.map((tag) => ({ value: tag.id, label: tag.name }));

  async function changeTags(tagIds: number[]) {
    const chosen = allTags.filter((tag) => tagIds.includes(tag.id));
    setNotice((await writer.setTags(chosen)) ?? "");
  }

  async function addTag(name: string): Promise<number | null> {
    const result = await createTag(projectId, name);
    if (!result.ok) {
      setNotice(result.message);
      return null;
    }
    setCreatedTags((prev) => [...prev, result.tag]);
    return result.tag.id;
  }

  async function submitNotePath(event: FormEvent) {
    event.preventDefault();
    const value = notePath.trim() === "" ? null : notePath.trim();
    if (value === submittedNotePath.current) return;
    submittedNotePath.current = value;
    const result = await writer.saveSourceNotePath(value);
    if (!result.ok) {
      submittedNotePath.current = content.source_note_path;
      setNotice(result.message);
      return;
    }
    submittedNotePath.current = result.value;
    setNotePath(result.value ?? "");
    setNotice("");
  }

  async function copyMine() {
    try {
      await navigator.clipboard.writeText(`# ${draft.title}\n\n${draft.body}`);
      setNotice("自分の内容をクリップボードにコピーしました");
    } catch {
      setNotice("コピーできませんでした。本文を選択して手でコピーしてください");
    }
  }

  async function discardAndReload() {
    if (!window.confirm("自分の編集を破棄して、最新の内容を読み込みます。よろしいですか？")) return;
    const latest = await writer.reloadLatest();
    setNotice(latest ? "" : "最新を読み込めませんでした");
    if (latest) {
      submittedNotePath.current = latest.source_note_path;
      setNotePath(latest.source_note_path ?? "");
    }
  }

  const chars = countChars(draft.body);

  return (
    <div className="flex flex-col gap-3">
      {/* 1行目：戻る・状態・保存状態 */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-3">
          <Link href={`/projects/${projectId}`} className="text-sm text-gray-500 hover:underline">
            ← カンバン
          </Link>
          <Menu
            label={`${STATUS_LABELS[content.status]} ▾`}
            items={(ALLOWED_TRANSITIONS[content.status] ?? []).map((to) => ({
              key: to,
              label: `${STATUS_LABELS[to]}へ`,
              onSelect: () => void writer.transition(to).then((e) => setNotice(e ?? "")),
            }))}
            emptyLabel="ここから動かせる先はありません"
          />
        </div>
        <div className="flex items-center gap-2 text-sm" aria-live="polite">
          <span
            className={
              status === "error" || status === "conflict"
                ? "text-red-600"
                : status === "dirty"
                  ? "text-amber-700"
                  : "text-gray-500"
            }
          >
            {STATUS_TEXT[status]}
            {status === "saved" && writer.savedAt && ` ${formatDateTime(writer.savedAt)}`}
          </span>
          {status === "error" && (
            <button type="button" onClick={() => void saveNow()} className="underline">
              再試行
            </button>
          )}
          {(status === "dirty" || status === "error") && (
            <button
              type="button"
              onClick={() => void saveNow()}
              className="rounded border border-gray-300 px-2 py-0.5"
            >
              保存（⌘S）
            </button>
          )}
        </div>
      </div>

      {status === "conflict" && (
        <div role="alert" className="flex flex-col gap-2 rounded border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          <p>
            他の画面でこのネタが更新されました。自動保存を止めています。
            あなたの編集はこの画面に残っています。
          </p>
          <div className="flex gap-2">
            <button type="button" onClick={() => void copyMine()} className="rounded border border-red-300 bg-white px-2 py-1">
              自分の内容をコピー
            </button>
            <button type="button" onClick={() => void discardAndReload()} className="rounded border border-red-300 bg-white px-2 py-1">
              最新を読み込む（自分の編集は破棄）
            </button>
          </div>
        </div>
      )}
      {status === "error" && writer.message && <p className="text-sm text-red-600">{writer.message}</p>}
      {notice !== "" && (
        <p aria-live="polite" className="text-sm text-gray-700">
          {notice}
        </p>
      )}

      {/* 2行目：タイトル */}
      <input
        value={draft.title}
        onChange={(event) => setDraft((d) => ({ ...d, title: event.target.value }))}
        maxLength={200}
        aria-label="タイトル"
        placeholder="タイトル"
        className="rounded border border-gray-300 px-3 py-2 text-lg font-bold"
      />

      {/* 3行目：タグ・元ノート（どちらも即保存。自動保存の対象外） */}
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <div className="flex flex-wrap items-center gap-1">
          {content.tags.map((tag) => (
            <span key={tag.id} className="rounded bg-gray-100 px-1.5 text-xs text-gray-700">
              #{tag.name}
            </span>
          ))}
          <CheckboxPicker
            label="タグ"
            options={tagOptions}
            selected={content.tags.map((t) => t.id)}
            onChange={(ids) => void changeTags(ids)}
            onCreate={addTag}
          />
        </div>
        <form onSubmit={submitNotePath} className="flex flex-1 items-center gap-1">
          <label htmlFor="source-note-path" className="text-gray-600">
            元ノート
          </label>
          <input
            id="source-note-path"
            value={notePath}
            onChange={(event) => setNotePath(event.target.value)}
            onBlur={(event) => void submitNotePath(event)}
            maxLength={500}
            placeholder="01_思いつき・日記・メモ/xxx.md"
            className="min-w-48 flex-1 rounded border border-gray-300 px-2 py-1"
          />
        </form>
      </div>

      {/* 本文 */}
      <div className={`grid gap-3 ${view === "split" ? "lg:grid-cols-2" : "grid-cols-1"}`}>
        {view !== "preview" && (
          <MarkdownEditor
            value={draft.body}
            onChange={(body) => setDraft((d) => ({ ...d, body }))}
          />
        )}
        {view !== "edit" && (
          <div
            className={`min-h-[60vh] overflow-y-auto rounded border border-gray-200 bg-white p-4 text-gray-900 ${
              view === "split" ? "hidden lg:block" : ""
            }`}
          >
            <MarkdownPreview markdown={draft.body} />
          </div>
        )}
      </div>

      {/* 下段：文字数・表示切り替え・履歴 */}
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="text-gray-600">
          本文 {chars.toLocaleString()} 文字
          <span className="ml-1 text-xs text-gray-500">（{CHAR_COUNT_NOTE}）</span>
        </span>
        <div className="flex items-center gap-2">
          <div role="group" aria-label="表示" className="flex overflow-hidden rounded border border-gray-300">
            {(
              [
                ["edit", "編集"],
                ["split", "並べて"],
                ["preview", "プレビュー"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                aria-pressed={view === value}
                onClick={() => setView(value)}
                // 幅が狭いときは「並べて」を出さない（design.md §9-5）
                className={`px-2 py-1 ${value === "split" ? "hidden lg:block" : ""} ${
                  view === value ? "bg-gray-900 text-white" : ""
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            type="button"
            aria-expanded={showHistory}
            onClick={() => setShowHistory((v) => !v)}
            className="rounded border border-gray-300 px-2 py-1"
          >
            履歴
          </button>
        </div>
      </div>

      {showHistory && (
        <RevisionPanel
          projectId={projectId}
          contentId={initial.id}
          memberNames={memberNames}
          onRestore={writer.restore}
        />
      )}
    </div>
  );
}
