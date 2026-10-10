"use server";

import { revalidatePath } from "next/cache";

import { apiFetch } from "@/lib/api/server";
import type { Tag } from "@/lib/api/types";

import type { ActionResult } from "../actions";

function message(status: number, code: string, fallback: string): string {
  if (code === "tag_name_conflict") return "同じ名前のタグがあります";
  if (status === 422) return "タグ名は1〜50文字です";
  if (status === 403) return "この操作の権限がありません";
  if (status === 404) return "タグが見つかりません。画面を読み込み直してください";
  if (status === 503) return "サーバーに接続できませんでした";
  return fallback;
}

/** リテラルのパスには type を付けない（revalidatePath の docs）。1つずつ指定する。 */
function revalidateBoth(projectId: number) {
  revalidatePath(`/projects/${projectId}`);
  revalidatePath(`/projects/${projectId}/tags`);
}

/** 改名。付与済みのネタすべてに反映される（content-pipeline C1）。 */
export async function renameTag(
  projectId: number,
  tagId: number,
  name: string,
): Promise<ActionResult> {
  const result = await apiFetch<Tag>(`/projects/${projectId}/tags/${tagId}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
  if (!result.ok) {
    return { ok: false, message: message(result.status, result.error.code, result.error.message) };
  }
  // カンバンのカードにもタグ名が出るので、両方を取り直させる。
  revalidateBoth(projectId);
  return { ok: true };
}

/** 削除。付いていたネタからは外れるが、ネタ自体は残る（C1）。 */
export async function deleteTag(projectId: number, tagId: number): Promise<ActionResult> {
  const result = await apiFetch<void>(`/projects/${projectId}/tags/${tagId}`, {
    method: "DELETE",
  });
  if (!result.ok) {
    return { ok: false, message: message(result.status, result.error.code, result.error.message) };
  }
  revalidateBoth(projectId);
  return { ok: true };
}
