import { HydrationBoundary, QueryClient, dehydrate } from "@tanstack/react-query";
import { notFound, redirect } from "next/navigation";

import { QueryProvider } from "@/components/providers/QueryProvider";
import { apiFetch, type ApiResult } from "@/lib/api/server";
import { queryKeys } from "@/lib/api/query-keys";
import {
  canWrite,
  type ChannelView,
  type Content,
  type Me,
  type Member,
  type Project,
  type TagWithUsage,
} from "@/lib/api/types";

import { ContentEditor } from "./ContentEditor";
import { ContentViewer } from "./ContentViewer";

/**
 * 編集画面 / 閲覧画面（content-pipeline design.md §9-2）。
 *
 * 取得はサーバーで行い、編集画面には初期データを HydrationBoundary で渡す
 * （ADR-0015 追記）。owner / editor かつ非 demo のときだけエディタを出す。
 * **これは UX のための出し分けで、防御は API の 403**（frontend.md §1）。
 */
export default async function ContentPage(props: PageProps<"/projects/[id]/contents/[cid]">) {
  const { id, cid } = await props.params;
  const projectId = Number(id);
  const contentId = Number(cid);
  if (!Number.isInteger(projectId) || !Number.isInteger(contentId)) {
    notFound();
  }

  const [project, content, tags, members, me, qiita] = await Promise.all([
    apiFetch<Project>(`/projects/${projectId}`),
    apiFetch<Content>(`/projects/${projectId}/contents/${contentId}`),
    apiFetch<TagWithUsage[]>(`/projects/${projectId}/tags`),
    apiFetch<Member[]>(`/projects/${projectId}/members`),
    apiFetch<Me>("/auth/me"),
    // 公開先のバッジ用（publishing design.md §13-1）。M1 のチャネルは Qiita だけ。
    apiFetch<ChannelView>(`/projects/${projectId}/contents/${contentId}/channels/qiita`),
  ]);
  for (const result of [project, content, tags, members, me, qiita] as ApiResult<unknown>[]) {
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
  if (!project.ok || !content.ok || !tags.ok || !members.ok || !me.ok || !qiita.ok) return null;
  const publications = qiita.data.publication ? [qiita.data.publication] : [];

  const memberNames = Object.fromEntries(
    members.data.map((member) => [member.user_id, member.display_name]),
  );

  // サーバー側の初期データ。リクエストごとに新しいクライアントを作る（使い回すと他人のデータが混ざる）。
  const queryClient = new QueryClient();
  queryClient.setQueryData(queryKeys.content(projectId, contentId), content.data);

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-6">
      <QueryProvider>
        <HydrationBoundary state={dehydrate(queryClient)}>
          {canWrite(project.data.role, me.data.is_demo) ? (
            <ContentEditor
              projectId={projectId}
              initial={content.data}
              tags={tags.data}
              memberNames={memberNames}
              publications={publications}
            />
          ) : (
            <ContentViewer
              projectId={projectId}
              content={content.data}
              memberNames={memberNames}
              publications={publications}
            />
          )}
        </HydrationBoundary>
      </QueryProvider>
    </main>
  );
}
