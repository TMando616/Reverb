"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import { CheckboxPicker } from "@/components/ui/CheckboxPicker";
import {
  STATUS_LABELS,
  STATUS_ORDER,
  type ContentStatus,
  type TagWithUsage,
} from "@/lib/api/types";

export type Filters = { tagIds: number[]; statuses: ContentStatus[]; q: string };

type Props = {
  tags: TagWithUsage[];
  initial: Filters;
};

/** 絞り込み条件 → 検索パラメータ。`?tag=3&tag=7&status=drafting&q=docker`（design.md §9-4）。 */
function toQuery({ tagIds, statuses, q }: Filters): string {
  const params = new URLSearchParams();
  for (const id of tagIds) params.append("tag", String(id));
  for (const status of statuses) params.append("status", status);
  if (q.trim() !== "") params.set("q", q.trim());
  const query = params.toString();
  return query === "" ? "" : `?${query}`;
}

/**
 * 絞り込みバー。条件は URL に置き、絞り込み自体はサーバー（API）で行う
 * （content-pipeline design.md §9-4）。ここは入力（クライアント状態）を持ち、
 * 確定したら URL を書き換えるだけ。ページの Server Component が新しい条件で取り直す。
 */
export function FilterBar({ tags, initial }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [filters, setFilters] = useState(initial);
  const [pending, startTransition] = useTransition();
  const debounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  // 待っている間にタグや状態が変わっても、最新の条件で反映するための参照。
  const latest = useRef(filters);
  useEffect(() => {
    latest.current = filters;
  });

  useEffect(() => () => clearTimeout(debounce.current), []);

  function apply(next: Filters) {
    setFilters(next);
    startTransition(() => {
      // pathname は自分のページ（/projects/[id]）。外から来た URL は使わない。
      router.replace(`${pathname}${toQuery(next)}`, { scroll: false });
    });
  }

  function changeKeyword(q: string) {
    setFilters((prev) => ({ ...prev, q }));
    clearTimeout(debounce.current);
    // 入力が 300ms 止まってから反映する（1文字ごとに取り直さない）。
    debounce.current = setTimeout(() => apply({ ...latest.current, q }), 300);
  }

  const active = filters.tagIds.length + filters.statuses.length + (filters.q.trim() ? 1 : 0);

  return (
    <div className="flex flex-wrap items-center gap-2" aria-busy={pending}>
      <CheckboxPicker
        label={`タグ${filters.tagIds.length > 0 ? `（${filters.tagIds.length}）` : ""}`}
        options={tags.map((tag) => ({ value: tag.id, label: tag.name }))}
        selected={filters.tagIds}
        onChange={(tagIds) => apply({ ...filters, tagIds })}
      />
      <CheckboxPicker
        label={`状態${filters.statuses.length > 0 ? `（${filters.statuses.length}）` : ""}`}
        options={STATUS_ORDER.map((status) => ({ value: status, label: STATUS_LABELS[status] }))}
        selected={filters.statuses}
        onChange={(statuses) => apply({ ...filters, statuses })}
      />
      <input
        type="search"
        value={filters.q}
        onChange={(event) => changeKeyword(event.target.value)}
        placeholder="キーワード（タイトル・本文）"
        maxLength={100}
        className="min-w-48 flex-1 rounded border border-gray-300 px-2 py-1 text-sm"
      />
      {active > 0 && (
        <button
          type="button"
          onClick={() => apply({ tagIds: [], statuses: [], q: "" })}
          className="text-sm text-gray-500 hover:underline"
        >
          条件をクリア
        </button>
      )}
      {pending && <span className="text-xs text-gray-500">絞り込み中…</span>}
    </div>
  );
}
