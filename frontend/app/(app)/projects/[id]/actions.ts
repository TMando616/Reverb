"use server";

import { revalidatePath } from "next/cache";

import { apiFetch } from "@/lib/api/server";
import type { Content, ContentStatus } from "@/lib/api/types";

export type ContentFormState = { message: string };

/** 作成と遷移で共通のもの。422 は意味が違う（入力不正 / 遷移不可）ので含めない。 */
function commonMessage(status: number, fallback: string): string {
  if (status === 403) return "この操作の権限がありません";
  if (status === 404) return "対象が見つかりません。画面を読み込み直してください";
  if (status === 503) return "サーバーに接続できませんでした";
  return fallback;
}

export async function createContent(
  projectId: number,
  _prev: ContentFormState,
  formData: FormData,
): Promise<ContentFormState> {
  const title = String(formData.get("title") ?? "").trim();
  if (title === "") {
    return { message: "タイトルを入力してください" };
  }

  const result = await apiFetch<Content>(`/projects/${projectId}/contents`, {
    method: "POST",
    body: JSON.stringify({ title, body_md: "" }),
  });

  if (!result.ok) {
    // 作成の 422 は入力が通らなかったということ（タイトルの長さなど）。
    const message =
      result.status === 422
        ? "タイトルが長すぎます（200文字まで）"
        : commonMessage(result.status, result.error.message);
    return { message };
  }

  revalidatePath(`/projects/${projectId}`);
  return { message: "" };
}

/**
 * 状態遷移。``expected_version`` は画面が表示している version をそのまま送る。
 * 古ければ API が 409 を返す（design.md §8-2）。可否の判定はここではしない。
 */
export async function transitionContent(
  projectId: number,
  _prev: ContentFormState,
  formData: FormData,
): Promise<ContentFormState> {
  const contentId = Number(formData.get("content_id"));
  const to = String(formData.get("to")) as ContentStatus;
  const expectedVersion = Number(formData.get("expected_version"));

  const result = await apiFetch<Content>(
    `/projects/${projectId}/contents/${contentId}/transition`,
    {
      method: "POST",
      body: JSON.stringify({ to, expected_version: expectedVersion }),
    },
  );

  if (!result.ok) {
    if (result.status === 409) {
      return { message: "他の人が先に更新しました。画面を読み込み直してください" };
    }
    if (result.status === 422) {
      return { message: "その状態へは進められません" };
    }
    return { message: commonMessage(result.status, result.error.message) };
  }

  revalidatePath(`/projects/${projectId}`);
  return { message: "" };
}
