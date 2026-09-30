"use client";

import { useActionState } from "react";

import { type AcceptState } from "./actions";

const initialState: AcceptState = { message: "" };

type Props = {
  /** ログイン済みかどうかで入力欄の有無が変わる（design.md §12-2）。 */
  loggedIn: boolean;
  action: (prev: AcceptState, formData: FormData) => Promise<AcceptState>;
};

export function InviteForm({ loggedIn, action }: Props) {
  const [state, formAction, pending] = useActionState(action, initialState);

  return (
    <form action={formAction} className="flex flex-col gap-4">
      {!loggedIn && (
        <>
          <label className="flex flex-col gap-1">
            <span className="text-sm">表示名</span>
            <input
              type="text"
              name="display_name"
              required
              className="rounded border border-gray-300 px-3 py-2"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-sm">パスワード</span>
            <input
              type="password"
              name="password"
              required
              autoComplete="new-password"
              className="rounded border border-gray-300 px-3 py-2"
            />
          </label>
        </>
      )}
      <p aria-live="polite" className="text-sm text-red-600">
        {state.message}
      </p>
      <button
        type="submit"
        disabled={pending}
        className="rounded bg-gray-900 px-4 py-2 text-white disabled:opacity-50"
      >
        {pending ? "処理中…" : "招待を受諾する"}
      </button>
    </form>
  );
}
