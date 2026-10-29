import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { apiFetch, type ApiResult } from "@/lib/api/server";
import {
  VISIBILITY_LABELS,
  formatDateTime,
  type Channel,
  type Project,
  type PublishedContent,
} from "@/lib/api/types";

/**
 * 企画の公開済み一覧（publishing C8・design.md §11）。どのネタがどのチャネルに出たか。
 * 取り消した公開物は出さない。取消は公開画面から行う。
 */
export default async function PublicationsPage(props: PageProps<"/projects/[id]/publications">) {
  const { id } = await props.params;
  const projectId = Number(id);
  if (!Number.isInteger(projectId)) {
    notFound();
  }

  const [project, entries, channels] = await Promise.all([
    apiFetch<Project>(`/projects/${projectId}`),
    apiFetch<PublishedContent[]>(`/projects/${projectId}/publications`),
    apiFetch<Channel[]>("/channels"),
  ]);
  for (const result of [project, entries, channels] as ApiResult<unknown>[]) {
    if (!result.ok) {
      if (result.status === 401) redirect("/login");
      if (result.status === 404) notFound();
      return (
        <main className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-10">
          <p className="text-sm text-red-600">
            読み込めませんでした（{result.status}: {result.error.code}）。
          </p>
        </main>
      );
    }
  }
  if (!project.ok || !entries.ok || !channels.ok) return null;

  const labels = Object.fromEntries(channels.data.map((c) => [c.code, c.label]));

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-10">
      <div className="flex flex-col gap-1">
        <Link href={`/projects/${projectId}`} className="text-sm text-gray-500 hover:underline">
          ← {project.data.name}
        </Link>
        <h1 className="text-xl font-bold">公開済み</h1>
      </div>
      {entries.data.length === 0 ? (
        <p className="text-sm text-gray-600">まだ公開したネタがありません。</p>
      ) : (
        <ul className="flex flex-col divide-y divide-gray-200">
          {entries.data.map((entry) => (
            <li key={entry.content_id} className="flex flex-col gap-1 py-3">
              <Link
                href={`/projects/${projectId}/contents/${entry.content_id}/publish`}
                className="font-bold hover:underline"
              >
                {entry.title}
              </Link>
              <ul className="flex flex-col gap-0.5 text-sm">
                {entry.publications.map((publication) => (
                  <li key={publication.id} className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-gray-100 px-1.5 text-xs">
                      {labels[publication.channel] ?? publication.channel}
                    </span>
                    <a
                      href={publication.url}
                      target="_blank"
                      rel="noreferrer"
                      className="break-all underline"
                    >
                      {publication.url}
                    </a>
                    {publication.visibility && (
                      <span className="text-xs text-gray-500">
                        {VISIBILITY_LABELS[publication.visibility]}
                      </span>
                    )}
                    <span className="text-xs text-gray-500">
                      {formatDateTime(publication.published_at)}
                    </span>
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
