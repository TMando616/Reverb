"use server";

import { revalidatePath } from "next/cache";

import { apiFetch } from "@/lib/api/server";
import type { Project } from "@/lib/api/types";

export type CreateProjectState = { message: string };

export async function createProject(
  _prev: CreateProjectState,
  formData: FormData,
): Promise<CreateProjectState> {
  const name = String(formData.get("name") ?? "").trim();
  if (name === "") {
    return { message: "企画名を入力してください" };
  }

  const result = await apiFetch<Project>("/projects", {
    method: "POST",
    body: JSON.stringify({ name }),
  });

  if (!result.ok) {
    if (result.status === 403) {
      return { message: "デモアカウントでは企画を作成できません" };
    }
    return { message: result.error.message };
  }

  // 一覧はサーバー状態なので、画面側に複製を持たず再取得で更新する（frontend.md §2）。
  revalidatePath("/projects");
  return { message: "" };
}
