"use client";

import { useActionState } from "react";

import { ALLOWED_TRANSITIONS, STATUS_LABELS, type Content } from "@/lib/api/types";

import type { ContentFormState } from "./actions";

const initialState: ContentFormState = { message: "" };

type Props = {
  content: Content;
  action: (prev: ContentFormState, formData: FormData) => Promise<ContentFormState>;
};

/**
 * 1行＋その行から進める先のボタン。表示する遷移先は ALLOWED_TRANSITIONS で絞るが、
 * 可否の最終判定は API 側（design.md §8-2）。ここで隠すのは操作を減らすためだけ。
 */
export function ContentRow({ content, action }: Props) {
  const [state, formAction, pending] = useActionState(action, initialState);

  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span>{content.title}</span>
        <span className="text-xs text-gray-500">v{content.version}</span>
      </div>
      <form action={formAction} className="flex flex-wrap items-center gap-2">
        <input type="hidden" name="content_id" value={content.id} />
        <input type="hidden" name="expected_version" value={content.version} />
        {ALLOWED_TRANSITIONS[content.status].map((to) => (
          <button
            key={to}
            type="submit"
            name="to"
            value={to}
            disabled={pending}
            className="rounded border border-gray-300 px-2 py-1 text-sm disabled:opacity-50"
          >
            {STATUS_LABELS[to]}へ
          </button>
        ))}
      </form>
      {state.message !== "" && (
        <p aria-live="polite" className="text-sm text-red-600">
          {state.message}
        </p>
      )}
    </li>
  );
}
