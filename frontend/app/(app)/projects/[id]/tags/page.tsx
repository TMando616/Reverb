import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { apiFetch, type ApiResult } from "@/lib/api/server";
import { canWrite, type Me, type Project, type TagWithUsage } from "@/lib/api/types";

import { TagRow } from "./TagRow";

/** タグの一覧・改名・削除（content-pipeline design.md §9-2）。作成はカンバンと編集画面から。 */
export default async function TagsPage(props: PageProps<"/projects/[id]/tags">) {
  const { id } = await props.params;
  const projectId = Number(id);
  if (!Number.isInteger(projectId)) {
    notFound();
  }

  const [project, tags, me] = await Promise.all([
    apiFetch<Project>(`/projects/${projectId}`),
    apiFetch<TagWithUsage[]>(`/projects/${projectId}/tags`),
    apiFetch<Me>("/auth/me"),
  ]);
  for (const result of [project, tags, me] as ApiResult<unknown>[]) {
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
  if (!project.ok || !tags.ok || !me.ok) return null;

  const writable = canWrite(project.data.role, me.data.is_demo);

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-10">
      <div className="flex flex-col gap-1">
        <Link href={`/projects/${projectId}`} className="text-sm text-gray-500 hover:underline">
          ← {project.data.name}
        </Link>
        <h1 className="text-xl font-bold">タグ</h1>
      </div>
      {tags.data.length === 0 ? (
        <p className="text-sm text-gray-600">
          まだタグがありません。ネタの登録・編集のときに作れます。
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-gray-200">
          {tags.data.map((tag) => (
            <TagRow key={tag.id} projectId={projectId} tag={tag} canWrite={writable} />
          ))}
        </ul>
      )}
    </main>
  );
}
