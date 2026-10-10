import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { apiFetch, type ApiResult } from "@/lib/api/server";
import {
  STATUS_ORDER,
  canWrite,
  type ContentStatus,
  type ContentSummary,
  type Me,
  type Project,
  type TagWithUsage,
} from "@/lib/api/types";

import { FilterBar, type Filters } from "./FilterBar";
import { KanbanBoard } from "./KanbanBoard";
import { NewContentDialog } from "./NewContentDialog";

type SearchParams = Record<string, string | string[] | undefined>;

function all(value: string | string[] | undefined): string[] {
  if (value === undefined) return [];
  return Array.isArray(value) ? value : [value];
}

/**
 * URL の検索パラメータ → 絞り込み条件（content-pipeline design.md §9-4）。
 * 形の合わない値は捨てる。API に投げると 422 でページごと落ちるため。
 */
function parseFilters(params: SearchParams): Filters {
  const tagIds = [
    ...new Set(all(params.tag).map(Number).filter((n) => Number.isInteger(n) && n > 0)),
  ];
  const statuses = [
    ...new Set(all(params.status).filter((s): s is ContentStatus =>
      (STATUS_ORDER as string[]).includes(s),
    )),
  ];
  const q = (all(params.q)[0] ?? "").slice(0, 100);
  return { tagIds, statuses, q };
}

function toApiQuery({ tagIds, statuses, q }: Filters): string {
  const params = new URLSearchParams();
  for (const id of tagIds) params.append("tag", String(id));
  for (const status of statuses) params.append("status", status);
  if (q.trim() !== "") params.set("q", q.trim());
  const query = params.toString();
  return query === "" ? "" : `?${query}`;
}

export default async function ProjectPage(props: PageProps<"/projects/[id]">) {
  const { id } = await props.params;
  const projectId = Number(id);
  // /projects/abc は NaN になる。API に投げると 422 で落ちるので、ここで 404 にする。
  if (!Number.isInteger(projectId)) {
    notFound();
  }
  const filters = parseFilters(await props.searchParams);

  const [project, contents, tags, me] = await Promise.all([
    apiFetch<Project>(`/projects/${projectId}`),
    apiFetch<ContentSummary[]>(`/projects/${projectId}/contents${toApiQuery(filters)}`),
    apiFetch<TagWithUsage[]>(`/projects/${projectId}/tags`),
    apiFetch<Me>("/auth/me"),
  ]);

  for (const result of [project, contents, tags, me] as ApiResult<unknown>[]) {
    if (!result.ok) {
      if (result.status === 401) redirect("/login");
      // 非メンバーには存在も伏せる（API が 404 を返す・foundation design.md §5-2）。
      if (result.status === 404) notFound();
      return (
        <main className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-10">
          <Link href="/projects" className="text-sm text-gray-500 hover:underline">
            ← 企画一覧
          </Link>
          <p className="text-sm text-red-600">
            読み込めませんでした（{result.status}: {result.error.code}）。
          </p>
        </main>
      );
    }
  }
  if (!project.ok || !contents.ok || !tags.ok || !me.ok) return null; // 上のループで抜けている

  const writable = canWrite(project.data.role, me.data.is_demo);
  const filtered = filters.tagIds.length + filters.statuses.length + (filters.q ? 1 : 0) > 0;

  return (
    <main className="flex w-full flex-col gap-4 px-4 py-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <Link href="/projects" className="text-sm text-gray-500 hover:underline">
            ← 企画一覧
          </Link>
          <h1 className="text-xl font-bold">{project.data.name}</h1>
        </div>
        <div className="flex items-center gap-3">
          <Link
            href={`/projects/${projectId}/tags`}
            className="text-sm text-gray-500 hover:underline"
          >
            タグの管理
          </Link>
          {writable && <NewContentDialog projectId={projectId} tags={tags.data} />}
        </div>
      </div>

      {/* key で作り直さない：キーワード入力中に URL が変わるたびに入力欄のフォーカスが外れる。
          入力中の条件は FilterBar のクライアント状態が正で、URL はその写し。 */}
      <FilterBar tags={tags.data} initial={filters} />

      {contents.data.length === 0 ? (
        <p className="text-sm text-gray-600">
          {filtered
            ? "条件に合うネタがありません。"
            : writable
              ? "まだネタがありません。「＋ ネタを登録」から追加できます。"
              : "まだネタがありません。"}
        </p>
      ) : (
        <KanbanBoard
          projectId={projectId}
          contents={contents.data}
          visibleStatuses={filters.statuses}
          canWrite={writable}
        />
      )}
    </main>
  );
}
