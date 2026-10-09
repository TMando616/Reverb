"use client";

import { Dialog as RadixDialog } from "radix-ui";
import type { ReactNode } from "react";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  children: ReactNode;
  /** 幅。本文のプレビューなど広く取りたいときは "wide"。 */
  size?: "normal" | "wide";
};

/**
 * モーダルダイアログ。フォーカスの閉じ込めと Esc で閉じる動きは Radix に任せる
 * （content-pipeline design.md §9-10）。開閉の状態は呼び出し側が持つ（クライアント状態）。
 */
export function Dialog({ open, onOpenChange, title, children, size = "normal" }: Props) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <RadixDialog.Content
          className={`fixed top-1/2 left-1/2 z-50 flex max-h-[85vh] w-[calc(100vw-2rem)] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 overflow-y-auto rounded bg-white p-5 text-gray-900 shadow-lg ${
            size === "wide" ? "max-w-3xl" : "max-w-md"
          }`}
        >
          <div className="flex items-start justify-between gap-4">
            <RadixDialog.Title className="text-base font-bold">{title}</RadixDialog.Title>
            <RadixDialog.Close aria-label="閉じる" className="text-gray-500 hover:text-gray-900">
              ×
            </RadixDialog.Close>
          </div>
          {/* 説明文を持たないダイアログなので、Radix の警告を明示的に外す。 */}
          <RadixDialog.Description className="sr-only">{title}</RadixDialog.Description>
          {children}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
