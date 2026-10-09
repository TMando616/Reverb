"use client";

import { DropdownMenu } from "radix-ui";
import type { ReactNode } from "react";

export type MenuItem = { key: string; label: ReactNode; onSelect: () => void; disabled?: boolean };

type Props = {
  /** ボタンに出す文字。 */
  label: ReactNode;
  items: MenuItem[];
  disabled?: boolean;
  /** 項目が無いときに出す文言。 */
  emptyLabel?: ReactNode;
};

/**
 * ボタン＋ドロップダウンメニュー。キーボード操作とフォーカス管理は Radix に任せる
 * （content-pipeline design.md §9-10）。ドメインを知らない（frontend.md §5）。
 */
export function Menu({ label, items, disabled, emptyLabel = "選べる項目がありません" }: Props) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger
        disabled={disabled}
        className="rounded border border-gray-300 px-2 py-1 text-sm disabled:opacity-50"
      >
        {label}
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={4}
          className="z-50 min-w-36 rounded border border-gray-200 bg-white p-1 text-sm text-gray-900 shadow-md"
        >
          {items.length === 0 && (
            <div className="px-2 py-1.5 text-gray-500">{emptyLabel}</div>
          )}
          {items.map((item) => (
            <DropdownMenu.Item
              key={item.key}
              disabled={item.disabled}
              onSelect={item.onSelect}
              className="cursor-pointer rounded px-2 py-1.5 outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-gray-100"
            >
              {item.label}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
