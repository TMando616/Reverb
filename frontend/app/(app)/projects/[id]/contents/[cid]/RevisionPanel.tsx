"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { MarkdownPreview } from "@/components/contents/MarkdownPreview";
import { Dialog } from "@/components/ui/Dialog";
import { bffFetch } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { formatDateTime, type Revision, type RevisionKind, type RevisionSummary } from "@/lib/api/types";

import type { RestoreOutcome } from "./use-content-writer";

const PAGE_SIZE = 50;

const KIND_LABELS: Record<RevisionKind, string> = {
  create: "作成",
  save: "保存",
  restore: "復元",
};

type Props = {
  projectId: number;
  contentId: number;
  /** user_id → 表示名。企画のメンバー一覧から引く（design.md §9-7）。 */
  memberNames: Record<number, string>;
  /** 渡されたときだけ [この版に戻す] を出す（owner / editor）。エラー文言を返す。 */
  onRestore?: (revisionNo: number) => Promise<RestoreOutcome>;
};

async function unwrap<T>(promise: ReturnType<typeof bffFetch<T>>): Promise<T> {
  const result = await promise;
  if (!result.ok) throw new Error(result.message);
  return result.data;
}

/** 版の一覧（新しい順・50件ずつ）と、選んだ版のプレビュー（content-pipeline C7）。 */
export function RevisionPanel({ projectId, contentId, memberNames, onRestore }: Props) {
  const base = `/projects/${projectId}/contents/${contentId}/revisions`;
  const [selected, setSelected] = useState<RevisionSummary | null>(null);
  const [message, setMessage] = useState("");
  const [restoring, setRestoring] = useState(false);

  const list = useInfiniteQuery({
    queryKey: queryKeys.revisions(projectId, contentId),
    queryFn: ({ pageParam }) =>
      unwrap(
        bffFetch<RevisionSummary[]>(
          `${base}?limit=${PAGE_SIZE}${pageParam ? `&before=${pageParam}` : ""}`,
        ),
      ),
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.length === PAGE_SIZE ? last[last.length - 1].revision_no : undefined,
    // 保存のたびに invalidate されるので、開いている間は常に新しい
    staleTime: 0,
  });

  const detail = useQuery({
    queryKey: queryKeys.revision(projectId, contentId, selected?.revision_no ?? 0),
    queryFn: () => unwrap(bffFetch<Revision>(`${base}/${selected?.revision_no}`)),
    enabled: selected !== null,
    // 版は追記専用で中身が変わらないので、一度取れば取り直さない
    staleTime: Infinity,
  });

  async function restore() {
    if (!selected || !onRestore) return;
    setRestoring(true);
    const outcome = await onRestore(selected.revision_no);
    setRestoring(false);
    if (!outcome.restored) {
      // キャンセル（message が null）のときはダイアログを開いたままにする
      if (outcome.message) setMessage(outcome.message);
      return;
    }
    setSelected(null);
  }

  const rows = list.data?.pages.flat() ?? [];

  return (
    <aside className="flex flex-col gap-2">
      <h2 className="text-sm font-bold text-gray-600">履歴</h2>
      {list.isPending && <p className="text-sm text-gray-500">読み込み中…</p>}
      {list.isError && <p className="text-sm text-red-600">履歴を読み込めませんでした</p>}
      <ul className="flex flex-col divide-y divide-gray-200 text-sm">
        {rows.map((row) => (
          <li key={row.revision_no}>
            <button
              type="button"
              onClick={() => {
                setMessage("");
                setSelected(row);
              }}
              className="flex w-full flex-col items-start gap-0.5 px-1 py-2 text-left hover:bg-gray-50"
            >
              <span>
                第{row.revision_no}版
                <span className="ml-2 text-xs text-gray-500">
                  {KIND_LABELS[row.kind]}
                  {row.restored_from_no !== null && `（第${row.restored_from_no}版から）`}
                </span>
              </span>
              <span className="text-xs text-gray-500">
                {formatDateTime(row.created_at)}・{memberNames[row.created_by] ?? "（退出したメンバー）"}・
                {row.body_length.toLocaleString()}文字
              </span>
            </button>
          </li>
        ))}
      </ul>
      {list.hasNextPage && (
        <button
          type="button"
          onClick={() => void list.fetchNextPage()}
          disabled={list.isFetchingNextPage}
          className="text-sm text-gray-500 hover:underline disabled:opacity-50"
        >
          さらに古い版を読む
        </button>
      )}

      <Dialog
        open={selected !== null}
        onOpenChange={(open) => !open && setSelected(null)}
        title={selected ? `第${selected.revision_no}版：${selected.title}` : ""}
        size="wide"
      >
        {detail.isPending && <p className="text-sm text-gray-500">読み込み中…</p>}
        {detail.isError && <p className="text-sm text-red-600">読み込めませんでした</p>}
        {detail.data && <MarkdownPreview markdown={detail.data.body_md} />}
        {message !== "" && (
          <p aria-live="polite" className="text-sm text-red-600">
            {message}
          </p>
        )}
        {onRestore && detail.data && (
          <button
            type="button"
            onClick={() => void restore()}
            disabled={restoring}
            className="self-end rounded bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            この版に戻す
          </button>
        )}
      </Dialog>
    </aside>
  );
}
