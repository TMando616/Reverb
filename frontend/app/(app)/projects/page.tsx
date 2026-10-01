import Link from "next/link";
import { redirect } from "next/navigation";

import { apiFetch } from "@/lib/api/server";
import type { Project } from "@/lib/api/types";

import { CreateProjectForm } from "./CreateProjectForm";

export default async function ProjectsPage() {
  // 一覧の取得はサーバー側で行う。Client Component の中でフェッチを始めない（frontend.md §3）。
  const result = await apiFetch<Project[]>("/projects");
  if (!result.ok) {
    if (result.status === 401) {
      redirect("/login");
    }
    // API が落ちている・繋がらないときは 500 ページにせず、何が起きたかを出す。
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-10">
        <h1 className="text-xl font-bold">企画</h1>
        <p className="text-sm text-red-600">
          企画を読み込めませんでした（{result.status}: {result.error.code}）。
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-10">
      <h1 className="text-xl font-bold">企画</h1>
      <CreateProjectForm />
      <ul className="flex flex-col divide-y divide-gray-200">
        {result.data.map((project) => (
          <li key={project.id} className="py-3">
            <Link href={`/projects/${project.id}`} className="flex justify-between hover:underline">
              <span>{project.name}</span>
              <span className="text-sm text-gray-500">{project.role}</span>
            </Link>
          </li>
        ))}
      </ul>
      {result.data.length === 0 && (
        <p className="text-sm text-gray-600">まだ企画がありません。上のフォームから作成できます。</p>
      )}
    </main>
  );
}
