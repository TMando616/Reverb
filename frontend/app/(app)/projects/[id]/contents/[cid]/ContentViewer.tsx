"use client";

import Link from "next/link";
import { useState } from "react";

import { countChars, CHAR_COUNT_NOTE } from "@/components/contents/char-count";
import { MarkdownPreview } from "@/components/contents/MarkdownPreview";
import { STATUS_LABELS, type Content, type Publication } from "@/lib/api/types";

import { PublishLink } from "./PublishLink";
import { RevisionPanel } from "./RevisionPanel";

type Props = {
  projectId: number;
  content: Content;
  memberNames: Record<number, string>;
  publications: Publication[];
  channelLabels: Record<string, string>;
};

/**
 * 閲覧画面（reviewer / demo）：プレビューと文字数、履歴の閲覧のみ（content-pipeline C5・C8）。
 * エディタは読み込まない。書き込みの API はどのみち 403 になる（frontend.md §1）。
 */
export function ContentViewer({
  projectId,
  content,
  memberNames,
  publications,
  channelLabels,
}: Props) {
  const [showHistory, setShowHistory] = useState(false);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-3 text-sm">
        <Link href={`/projects/${projectId}`} className="text-gray-500 hover:underline">
          ← カンバン
        </Link>
        <span className="rounded border border-gray-300 px-2 py-0.5">
          {STATUS_LABELS[content.status]}
        </span>
        <span className="text-gray-500">閲覧のみ</span>
        <PublishLink
          projectId={projectId}
          contentId={content.id}
          publications={publications}
          channelLabels={channelLabels}
        />
      </div>
      <h1 className="text-xl font-bold">{content.title}</h1>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {content.tags.map((tag) => (
          <span key={tag.id} className="rounded bg-gray-100 px-1.5 text-xs text-gray-700">
            #{tag.name}
          </span>
        ))}
        {content.source_note_path && (
          <span className="text-gray-600">元ノート：{content.source_note_path}</span>
        )}
      </div>
      <div className="rounded border border-gray-200 bg-white p-4 text-gray-900">
        <MarkdownPreview markdown={content.body_md} />
      </div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-gray-600">
          本文 {countChars(content.body_md).toLocaleString()} 文字
          <span className="ml-1 text-xs text-gray-500">（{CHAR_COUNT_NOTE}）</span>
        </span>
        <button
          type="button"
          aria-expanded={showHistory}
          onClick={() => setShowHistory((v) => !v)}
          className="rounded border border-gray-300 px-2 py-1"
        >
          履歴
        </button>
      </div>
      {showHistory && (
        <RevisionPanel projectId={projectId} contentId={content.id} memberNames={memberNames} />
      )}
    </div>
  );
}
