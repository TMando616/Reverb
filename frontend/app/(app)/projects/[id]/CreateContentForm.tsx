"use client";

import { useActionState } from "react";

import type { ContentFormState } from "./actions";

const initialState: ContentFormState = { message: "" };

type Props = {
  action: (prev: ContentFormState, formData: FormData) => Promise<ContentFormState>;
};

export function CreateContentForm({ action }: Props) {
  const [state, formAction, pending] = useActionState(action, initialState);

  return (
    <form action={formAction} className="flex flex-col gap-2">
      <div className="flex gap-2">
        <input
          type="text"
          name="title"
          required
          placeholder="新しいネタのタイトル"
          className="flex-1 rounded border border-gray-300 px-3 py-2"
        />
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-gray-900 px-4 py-2 text-white disabled:opacity-50"
        >
          追加
        </button>
      </div>
      <p aria-live="polite" className="text-sm text-red-600">
        {state.message}
      </p>
    </form>
  );
}
