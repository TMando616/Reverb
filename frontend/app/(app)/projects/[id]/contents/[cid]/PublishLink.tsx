import Link from "next/link";

import type { Publication } from "@/lib/api/types";

type Props = { projectId: number; contentId: number; publications: Publication[] };

/** 編集・閲覧画面のヘッダに置く、公開画面への導線と公開先のバッジ（publishing design.md §13-1）。 */
export function PublishLink({ projectId, contentId, publications }: Props) {
  return (
    <span className="flex items-center gap-2 text-sm">
      <Link
        href={`/projects/${projectId}/contents/${contentId}/publish`}
        className="rounded border border-gray-300 px-2 py-0.5 hover:bg-gray-50"
      >
        公開へ
      </Link>
      {publications.map((publication) => (
        <a
          key={publication.id}
          href={publication.url}
          target="_blank"
          rel="noreferrer"
          title={publication.url}
          className="rounded bg-green-100 px-1.5 text-xs text-green-800"
        >
          {publication.channel === "qiita" ? "Qiita" : publication.channel} 公開中
        </a>
      ))}
    </span>
  );
}
