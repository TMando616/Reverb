"use client";

import { useActionState } from "react";

import { createProject, type CreateProjectState } from "./actions";

const initialState: CreateProjectState = { message: "" };

export function CreateProjectForm() {
  const [state, formAction, pending] = useActionState(createProject, initialState);

  return (
    <form action={formAction} className="flex flex-col gap-2">
      <div className="flex gap-2">
        <input
          type="text"
          name="name"
          required
          placeholder="新しい企画名"
          className="flex-1 rounded border border-gray-300 px-3 py-2"
        />
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-gray-900 px-4 py-2 text-white disabled:opacity-50"
        >
          作成
        </button>
      </div>
      <p aria-live="polite" className="text-sm text-red-600">
        {state.message}
      </p>
    </form>
  );
}
