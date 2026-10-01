import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { apiFetch } from "@/lib/api/server";
import {
  STATUS_LABELS,
  type Content,
  type ContentStatus,
  type Project,
} from "@/lib/api/types";

import { createContent, transitionContent, type ContentFormState } from "./actions";
import { ContentRow } from "./ContentRow";
import { CreateContentForm } from "./CreateContentForm";

const STATUS_ORDER: ContentStatus[] = [
  "inbox",
  "adopted",
  "drafting",
  "in_review",
  "published",
  "shelved",
];

export default async function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const projectId = Number(id);
  // /projects/abc は NaN になる。API に投げると 422 で落ちるので、ここで 404 にする。
  if (!Number.isInteger(projectId)) {
    notFound();
  }

  const [project, contents] = await Promise.all([
    apiFetch<Project>(`/projects/${projectId}`),
    apiFetch<Content[]>(`/projects/${projectId}/contents`),
  ]);

  for (const result of [project, contents]) {
    if (!result.ok) {
      if (result.status === 401) redirect("/login");
      // 非メンバーには存在も伏せる（API が 404 を返す・design.md §5-2）。
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
  if (!project.ok || !contents.ok) return null; // 上のループで抜けているので到達しない

  async function create(prev: ContentFormState, formData: FormData) {
    "use server";
    return createContent(projectId, prev, formData);
  }

  async function transition(prev: ContentFormState, formData: FormData) {
    "use server";
    return transitionContent(projectId, prev, formData);
  }

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-10">
      <div className="flex flex-col gap-1">
        <Link href="/projects" className="text-sm text-gray-500 hover:underline">
          ← 企画一覧
        </Link>
        <h1 className="text-xl font-bold">{project.data.name}</h1>
      </div>

      <CreateContentForm action={create} />

      {STATUS_ORDER.map((status) => {
        const rows = contents.data.filter((content) => content.status === status);
        if (rows.length === 0) return null;
        return (
          <section key={status} className="flex flex-col gap-1">
            <h2 className="text-sm font-bold text-gray-600">
              {STATUS_LABELS[status]}（{rows.length}）
            </h2>
            <ul className="flex flex-col divide-y divide-gray-200">
              {rows.map((content) => (
                <ContentRow key={content.id} content={content} action={transition} />
              ))}
            </ul>
          </section>
        );
      })}

      {contents.data.length === 0 && (
        <p className="text-sm text-gray-600">まだネタがありません。上のフォームから追加できます。</p>
      )}
    </main>
  );
}
