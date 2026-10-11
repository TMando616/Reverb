"use client";

import dynamic from "next/dynamic";

// CodeMirror はブラウザの DOM を前提にするので、サーバーでは描画しない（ADR-0016 §影響）。
// `ssr: false` は Client Component の中でしか使えない（next/dist/docs …/lazy-loading.md）。
const CodeMirrorField = dynamic(() => import("./CodeMirrorField"), {
  ssr: false,
  loading: () => <div className="min-h-[60vh] animate-pulse rounded bg-gray-100" />,
});

export function MarkdownEditor(props: { value: string; onChange: (value: string) => void }) {
  return <CodeMirrorField {...props} />;
}
