"use client";

import { useState, useTransition, type FormEvent } from "react";

import { CheckboxPicker } from "@/components/ui/CheckboxPicker";
import { Dialog } from "@/components/ui/Dialog";
import type { Tag } from "@/lib/api/types";

import { createContent, createTag } from "./actions";

type Props = { projectId: number; tags: Tag[] };

/**
 * ネタの登録ダイアログ：タイトル（必須）・タグ（その場で作成可）・メモ（content-pipeline C2）。
 * メモは本文（body_md）の初期値になる（design.md §9-3）。
 */
export function NewContentDialog({ projectId, tags }: Props) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [memo, setMemo] = useState("");
  const [tagIds, setTagIds] = useState<number[]>([]);
  // その場で作ったタグ。ページの再取得が届くまでの間も選択肢に出すため。
  const [created, setCreated] = useState<Tag[]>([]);
  const [message, setMessage] = useState("");
  const [pending, startTransition] = useTransition();

  const options = [...tags, ...created.filter((c) => !tags.some((t) => t.id === c.id))].map(
    (tag) => ({ value: tag.id, label: tag.name }),
  );

  function reset() {
    setTitle("");
    setMemo("");
    setTagIds([]);
    setCreated([]);
    setMessage("");
  }

  async function addTag(name: string): Promise<number | null> {
    const result = await createTag(projectId, name);
    if (!result.ok) {
      setMessage(result.message);
      return null;
    }
    setCreated((prev) => [...prev, result.tag]);
    return result.tag.id;
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    startTransition(async () => {
      const result = await createContent(projectId, { title, memo, tagIds });
      if (!result.ok) {
        setMessage(result.message);
        return;
      }
      reset();
      setOpen(false);
    });
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded bg-gray-900 px-3 py-1.5 text-sm text-white"
      >
        ＋ ネタを登録
      </button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) reset();
        }}
        title="ネタを登録"
      >
        <form onSubmit={submit} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-sm">
            タイトル
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              required
              maxLength={200}
              autoFocus
              className="rounded border border-gray-300 px-3 py-2"
            />
          </label>
          <div className="flex items-center gap-2 text-sm">
            <span>タグ</span>
            <CheckboxPicker
              label={tagIds.length > 0 ? `${tagIds.length}個選択中` : "選ぶ"}
              options={options}
              selected={tagIds}
              onChange={setTagIds}
              onCreate={addTag}
            />
          </div>
          <label className="flex flex-col gap-1 text-sm">
            メモ（本文の書き出しになります）
            <textarea
              value={memo}
              onChange={(event) => setMemo(event.target.value)}
              rows={5}
              className="rounded border border-gray-300 px-3 py-2"
            />
          </label>
          {message !== "" && (
            <p aria-live="polite" className="text-sm text-red-600">
              {message}
            </p>
          )}
          <button
            type="submit"
            disabled={pending}
            className="self-end rounded bg-gray-900 px-4 py-2 text-sm text-white disabled:opacity-50"
          >
            登録
          </button>
        </form>
      </Dialog>
    </>
  );
}
