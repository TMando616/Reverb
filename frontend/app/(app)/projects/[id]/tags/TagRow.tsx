"use client";

import { useState, useTransition, type FormEvent } from "react";

import type { TagWithUsage } from "@/lib/api/types";

import { deleteTag, renameTag } from "./actions";

type Props = { projectId: number; tag: TagWithUsage; canWrite: boolean };

/** タグ1行：名前・使用件数・改名・削除（content-pipeline C1）。 */
export function TagRow({ projectId, tag, canWrite }: Props) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(tag.name);
  const [message, setMessage] = useState("");
  const [pending, startTransition] = useTransition();

  function rename(event: FormEvent) {
    event.preventDefault();
    startTransition(async () => {
      const result = await renameTag(projectId, tag.id, name);
      if (!result.ok) {
        setMessage(result.message);
        return;
      }
      setMessage("");
      setEditing(false);
    });
  }

  function remove() {
    const note = tag.content_count > 0 ? `\n付いている ${tag.content_count} 件のネタから外れます（ネタは消えません）。` : "";
    if (!window.confirm(`「${tag.name}」を削除しますか？${note}`)) return;
    startTransition(async () => {
      const result = await deleteTag(projectId, tag.id);
      if (!result.ok) setMessage(result.message);
    });
  }

  return (
    <li className="flex flex-col gap-1 py-2">
      <div className="flex items-center justify-between gap-3">
        {editing ? (
          <form onSubmit={rename} className="flex flex-1 gap-2">
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={50}
              autoFocus
              className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm"
            />
            <button
              type="submit"
              disabled={pending}
              className="rounded bg-gray-900 px-3 py-1 text-sm text-white disabled:opacity-50"
            >
              保存
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(false);
                setName(tag.name);
                setMessage("");
              }}
              className="text-sm text-gray-500"
            >
              やめる
            </button>
          </form>
        ) : (
          <span>
            #{tag.name} <span className="text-xs text-gray-500">（{tag.content_count}件）</span>
          </span>
        )}
        {canWrite && !editing && (
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setEditing(true)}
              className="rounded border border-gray-300 px-2 py-1 text-sm"
            >
              名前を変える
            </button>
            <button
              type="button"
              onClick={remove}
              disabled={pending}
              className="rounded border border-red-300 px-2 py-1 text-sm text-red-700 disabled:opacity-50"
            >
              削除
            </button>
          </div>
        )}
      </div>
      {message !== "" && (
        <p aria-live="polite" className="text-sm text-red-600">
          {message}
        </p>
      )}
    </li>
  );
}
