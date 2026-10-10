"use client";

import Link from "next/link";
import { startTransition, useOptimistic, useState } from "react";

import { Menu } from "@/components/ui/Menu";
import {
  ALLOWED_TRANSITIONS,
  STATUS_LABELS,
  STATUS_ORDER,
  formatDateTime,
  type ContentStatus,
  type ContentSummary,
} from "@/lib/api/types";

import { transitionContent } from "./actions";

type Props = {
  projectId: number;
  contents: ContentSummary[];
  /** 状態で絞り込んでいるときは、選んだ列だけを出す。空なら全列。 */
  visibleStatuses: ContentStatus[];
  canWrite: boolean;
};

type Move = { contentId: number; to: ContentStatus };

/**
 * 6状態のカンバン（content-pipeline design.md §9-3）。
 *
 * 状態変更は「移動」メニューから。`useOptimistic` で先にカードを動かし、Server Action が
 * 失敗したら元の列に戻して理由を出す。可否の最終判定は API（422）で、メニューに
 * 遷移できる先だけを出すのは操作を減らすため。
 */
export function KanbanBoard({ projectId, contents, visibleStatuses, canWrite }: Props) {
  const [optimistic, applyMove] = useOptimistic(contents, (current, move: Move) =>
    current.map((c) => (c.id === move.contentId ? { ...c, status: move.to } : c)),
  );
  // カードごとの失敗メッセージ。サーバー状態ではないのでローカルに閉じる（frontend.md §2）。
  const [errors, setErrors] = useState<Record<number, string>>({});

  function move(content: ContentSummary, to: ContentStatus) {
    setErrors((prev) => {
      const next = { ...prev };
      delete next[content.id];
      return next;
    });
    startTransition(async () => {
      applyMove({ contentId: content.id, to });
      const result = await transitionContent(projectId, content.id, to, content.version);
      if (!result.ok) {
        setErrors((prev) => ({ ...prev, [content.id]: result.message }));
      }
    });
  }

  const columns = visibleStatuses.length > 0 ? visibleStatuses : STATUS_ORDER;

  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex gap-3">
        {STATUS_ORDER.filter((status) => columns.includes(status)).map((status) => {
          const cards = optimistic.filter((c) => c.status === status);
          return (
            <section
              key={status}
              aria-label={STATUS_LABELS[status]}
              className="flex w-64 shrink-0 flex-col gap-2 rounded bg-gray-50 p-2"
            >
              <h2 className="px-1 text-sm font-bold text-gray-600">
                {STATUS_LABELS[status]}（{cards.length}）
              </h2>
              <ul className="flex flex-col gap-2">
                {cards.map((content) => (
                  <li
                    key={content.id}
                    className="flex flex-col gap-2 rounded border border-gray-200 bg-white p-2 text-gray-900"
                  >
                    <Link
                      href={`/projects/${projectId}/contents/${content.id}`}
                      className="font-medium hover:underline"
                    >
                      {content.title}
                    </Link>
                    {content.tags.length > 0 && (
                      <ul className="flex flex-wrap gap-1">
                        {content.tags.map((tag) => (
                          <li key={tag.id} className="rounded bg-gray-100 px-1.5 text-xs text-gray-700">
                            #{tag.name}
                          </li>
                        ))}
                      </ul>
                    )}
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs text-gray-500">
                        {formatDateTime(content.updated_at)} 更新
                      </span>
                      {canWrite && (
                        <Menu
                          label="移動"
                          items={(ALLOWED_TRANSITIONS[content.status] ?? []).map((to) => ({
                            key: to,
                            label: `${STATUS_LABELS[to]}へ`,
                            onSelect: () => move(content, to),
                          }))}
                          emptyLabel="ここから動かせる先はありません"
                        />
                      )}
                    </div>
                    {errors[content.id] && (
                      <p aria-live="polite" className="text-xs text-red-600">
                        {errors[content.id]}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </div>
  );
}
