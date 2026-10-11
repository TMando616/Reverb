"use client";

import { markdown } from "@codemirror/lang-markdown";
import CodeMirror, { EditorView } from "@uiw/react-codemirror";

type Props = { value: string; onChange: (value: string) => void };

// 拡張は描画のたびに作り直さない（作り直すとエディタが再構成され、カーソルが飛ぶ）。
const extensions = [markdown(), EditorView.lineWrapping];

/**
 * Markdown エディタ本体（ADR-0016：CodeMirror 6）。テキストをそのまま編集するので、
 * 保存される文字列 ＝ 打った文字列になる。`MarkdownEditor` から `ssr: false` で読み込む。
 */
export default function CodeMirrorField({ value, onChange }: Props) {
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      extensions={extensions}
      basicSetup={{ foldGutter: false, highlightActiveLine: false }}
      minHeight="60vh"
      className="text-sm"
      aria-label="本文"
    />
  );
}
