"use server";

import { revalidatePath } from "next/cache";

import { apiFetch } from "@/lib/api/server";
import type { Content, ContentStatus, Tag } from "@/lib/api/types";

/** 画面に出す結果。失敗時だけ message が入る。 */
export type ActionResult = { ok: true } | { ok: false; message: string };

/** 作成・遷移・タグで共通のもの。422 / 409 は操作ごとに意味が違うので含めない。 */
function commonMessage(status: number, fallback: string): string {
  if (status === 401) return "ログインし直してください";
  if (status === 403) return "この操作の権限がありません";
  if (status === 404) return "対象が見つかりません。画面を読み込み直してください";
  if (status === 503) return "サーバーに接続できませんでした";
  return fallback;
}

export type NewContentInput = { title: string; memo: string; tagIds: number[] };

/**
 * カンバンからのネタ登録（content-pipeline design.md §9-3）。
 * メモは本文（body_md）の初期値として入れる。
 */
export async function createContent(
  projectId: number,
  input: NewContentInput,
): Promise<ActionResult> {
  const title = input.title.trim();
  if (title === "") {
    return { ok: false, message: "タイトルを入力してください" };
  }

  const result = await apiFetch<Content>(`/projects/${projectId}/contents`, {
    method: "POST",
    body: JSON.stringify({ title, body_md: input.memo, tag_ids: input.tagIds }),
  });

  if (!result.ok) {
    if (result.status === 422) {
      return {
        ok: false,
        message:
          result.error.code === "invalid_tag"
            ? "選んだタグが使えません。画面を読み込み直してください"
            : "入力が長すぎます（タイトルは200文字まで）",
      };
    }
    return { ok: false, message: commonMessage(result.status, result.error.message) };
  }

  revalidatePath(`/projects/${projectId}`);
  return { ok: true };
}

/**
 * 状態遷移。``expected_version`` は画面が表示している version をそのまま送る。
 * 古ければ API が 409 を返す（foundation design.md §8-2）。可否の判定はここではしない。
 */
export async function transitionContent(
  projectId: number,
  contentId: number,
  to: ContentStatus,
  expectedVersion: number,
): Promise<ActionResult> {
  const result = await apiFetch<Content>(
    `/projects/${projectId}/contents/${contentId}/transition`,
    {
      method: "POST",
      body: JSON.stringify({ to, expected_version: expectedVersion }),
    },
  );

  if (!result.ok) {
    if (result.status === 409) {
      return { ok: false, message: "他の人が先に更新しました。画面を読み込み直してください" };
    }
    if (result.status === 422) {
      return { ok: false, message: "その状態へは進められません" };
    }
    return { ok: false, message: commonMessage(result.status, result.error.message) };
  }

  revalidatePath(`/projects/${projectId}`);
  return { ok: true };
}

export type CreateTagResult = { ok: true; tag: Tag } | { ok: false; message: string };

/** 登録ダイアログ・編集画面から、その場でタグを作る。 */
export async function createTag(projectId: number, name: string): Promise<CreateTagResult> {
  const result = await apiFetch<Tag>(`/projects/${projectId}/tags`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });

  if (!result.ok) {
    if (result.error.code === "tag_name_conflict") {
      return { ok: false, message: "同じ名前のタグがあります" };
    }
    if (result.status === 422) {
      return { ok: false, message: "タグ名は50文字までです" };
    }
    return { ok: false, message: commonMessage(result.status, result.error.message) };
  }

  revalidatePath(`/projects/${projectId}`);
  return { ok: true, tag: result.data };
}
