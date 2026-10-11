"use client";

import { useEffect } from "react";

const MESSAGE = "保存していない変更があります。このページを離れますか？";

/**
 * 未保存の変更があるまま離れようとしたら確かめる（content-pipeline C6・design.md §9-6）。
 *
 * - タブを閉じる・再読み込み・外部へ移動：`beforeunload`（文言はブラウザ既定のものになる）
 * - アプリ内のリンク（`next/link` を含む）：document のキャプチャ段階でクリックを拾う。
 *   React のイベントはルート要素で受けるので、document のキャプチャが先に走り、
 *   ここで止めれば `<Link>` の遷移も起きない
 */
export function useLeaveGuard(active: boolean) {
  useEffect(() => {
    if (!active) return;

    function onBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
    }

    function onClick(event: MouseEvent) {
      // 新しいタブで開く操作はこのページを離れない。
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = (event.target as Element | null)?.closest?.("a[href]");
      if (!(anchor instanceof HTMLAnchorElement) || anchor.target === "_blank") return;
      if (anchor.origin !== window.location.origin) return; // 外部は beforeunload に任せる
      if (anchor.pathname === window.location.pathname) return;
      if (!window.confirm(MESSAGE)) {
        event.preventDefault();
        event.stopPropagation();
      }
    }

    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [active]);
}
