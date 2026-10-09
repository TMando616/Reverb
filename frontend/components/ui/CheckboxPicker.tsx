"use client";

import { Popover } from "radix-ui";
import { useState, type FormEvent, type ReactNode } from "react";

export type PickerOption<T extends string | number> = { value: T; label: string };

type Props<T extends string | number> = {
  label: ReactNode;
  options: PickerOption<T>[];
  selected: T[];
  onChange: (selected: T[]) => void;
  /** 渡すと、一覧に無い名前をその場で作れる入力欄が出る。作った項目の value を返す。 */
  onCreate?: (name: string) => Promise<T | null>;
  disabled?: boolean;
};

/**
 * 複数選択のポップオーバー（チェックボックスの一覧）。
 * 選択状態は呼び出し側が持ち、ここは表示と操作だけ（frontend.md §2 のクライアント状態）。
 */
export function CheckboxPicker<T extends string | number>({
  label,
  options,
  selected,
  onChange,
  onCreate,
  disabled,
}: Props<T>) {
  const [draft, setDraft] = useState("");
  const [creating, setCreating] = useState(false);

  function toggle(value: T) {
    onChange(
      selected.includes(value) ? selected.filter((v) => v !== value) : [...selected, value],
    );
  }

  async function create(event: FormEvent) {
    event.preventDefault();
    const name = draft.trim();
    if (!onCreate || name === "") return;
    setCreating(true);
    try {
      const value = await onCreate(name);
      if (value !== null) {
        onChange([...selected, value]);
        setDraft("");
      }
    } finally {
      setCreating(false);
    }
  }

  return (
    <Popover.Root>
      <Popover.Trigger
        disabled={disabled}
        className="rounded border border-gray-300 px-2 py-1 text-sm disabled:opacity-50"
      >
        {label}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={4}
          className="z-50 flex max-h-80 w-60 flex-col gap-2 overflow-y-auto rounded border border-gray-200 bg-white p-2 text-sm text-gray-900 shadow-md"
        >
          {options.length === 0 && <p className="px-1 text-gray-500">まだありません</p>}
          {options.map((option) => (
            <label key={String(option.value)} className="flex cursor-pointer items-center gap-2 px-1">
              <input
                type="checkbox"
                checked={selected.includes(option.value)}
                onChange={() => toggle(option.value)}
              />
              {option.label}
            </label>
          ))}
          {onCreate && (
            <form onSubmit={create} className="flex gap-1 border-t border-gray-200 pt-2">
              <input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="新しく作る"
                maxLength={50}
                className="min-w-0 flex-1 rounded border border-gray-300 px-2 py-1"
              />
              <button
                type="submit"
                disabled={creating || draft.trim() === ""}
                className="rounded bg-gray-900 px-2 py-1 text-white disabled:opacity-50"
              >
                追加
              </button>
            </form>
          )}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
