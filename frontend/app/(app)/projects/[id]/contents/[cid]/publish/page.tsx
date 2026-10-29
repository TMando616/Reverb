import { HydrationBoundary, QueryClient, dehydrate } from "@tanstack/react-query";
import { notFound, redirect } from "next/navigation";

import { QueryProvider } from "@/components/providers/QueryProvider";
import { apiFetch, type ApiResult } from "@/lib/api/server";
import { queryKeys } from "@/lib/api/query-keys";
import {
  canPublish,
  canWrite,
  type ChannelView,
  type Content,
  type Me,
  type Project,
  type QiitaAccount,
} from "@/lib/api/types";

import { PublishScreen } from "./PublishScreen";

/**
 * 公開画面（publishing design.md §13）。編集画面とは分ける（原稿用のエディタとバッファを
 * 編集画面に足すと、どちらを保存しているのかが曖昧になるため）。
 * 取得はサーバーで行い、公開画面のまとめは HydrationBoundary で渡す（ADR-0015 追記）。
 */
export default async function PublishPage(
  props: PageProps<"/projects/[id]/contents/[cid]/publish">,
) {
  const { id, cid } = await props.params;
  const projectId = Number(id);
  const contentId = Number(cid);
  if (!Number.isInteger(projectId) || !Number.isInteger(contentId)) {
    notFound();
  }

  const [project, content, view, me, qiita] = await Promise.all([
    apiFetch<Project>(`/projects/${projectId}`),
    apiFetch<Content>(`/projects/${projectId}/contents/${contentId}`),
    apiFetch<ChannelView>(`/projects/${projectId}/contents/${contentId}/channels/qiita`),
    apiFetch<Me>("/auth/me"),
    apiFetch<QiitaAccount>("/me/accounts/qiita"),
  ]);
  for (const result of [project, content, view, me, qiita] as ApiResult<unknown>[]) {
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
  if (!project.ok || !content.ok || !view.ok || !me.ok || !qiita.ok) return null;

  const queryClient = new QueryClient();
  queryClient.setQueryData(queryKeys.channel(projectId, contentId, "qiita"), view.data);

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-4 px-4 py-6">
      <QueryProvider>
        <HydrationBoundary state={dehydrate(queryClient)}>
          <PublishScreen
            projectId={projectId}
            contentId={contentId}
            title={content.data.title}
            status={content.data.status}
            initial={view.data}
            canWrite={canWrite(project.data.role, me.data.is_demo)}
            canPublish={canPublish(project.data.role, me.data.is_demo)}
            qiitaRegistered={qiita.data.registered}
          />
        </HydrationBoundary>
      </QueryProvider>
    </main>
  );
}
