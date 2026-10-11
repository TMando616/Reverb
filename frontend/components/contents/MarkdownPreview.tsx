import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/**
 * Markdown のプレビュー（content-pipeline design.md §9-8・ADR-0016）。
 *
 * **`rehype-raw` を入れない。** 本文中の HTML はタグとして解釈されず文字として出る。
 * `javascript:` などの危険なリンクは react-markdown 既定の URL 変換で無効になる。
 * reviewer / demo も他人の本文をここで描画するので、ここを緩めると XSS になる。
 */
export function MarkdownPreview({ markdown }: { markdown: string }) {
  return (
    <div className="markdown-preview">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  );
}
