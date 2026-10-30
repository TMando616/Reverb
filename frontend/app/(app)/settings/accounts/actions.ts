"use server";

import { revalidatePath } from "next/cache";

import { apiFetch } from "@/lib/api/server";
import type { QiitaAccount } from "@/lib/api/types";

import type { ActionResult } from "../../projects/[id]/actions";

function message(status: number, code: string): string {
  if (code === "invalid_qiita_token") {
    return "Qiita がこのトークンを受け付けませんでした。write_qiita スコープで発行したか確認してください";
  }
  if (code === "misconfigured") {
    return "サーバーの設定（トークンを暗号化する鍵）が足りないため登録できません。管理者に連絡してください";
  }
  if (code === "qiita_unavailable" || code === "qiita_rate_limited") {
    return "Qiita に確認できませんでした。少し待ってからもう一度試してください";
  }
  if (status === 401) return "ログインし直してください";
  if (status === 403) return "デモアカウントではトークンを登録できません";
  if (status === 422) return "トークンを入力してください";
  if (status === 503) return "サーバーに接続できませんでした";
  return "登録できませんでした";
}

/** 登録・差し替え。サーバーが Qiita に問い合わせて確かめてから暗号化して保存する（C5）。 */
export async function registerQiitaToken(token: string): Promise<ActionResult> {
  const trimmed = token.trim();
  if (trimmed === "") return { ok: false, message: "トークンを入力してください" };
  const result = await apiFetch<QiitaAccount>("/me/accounts/qiita", {
    method: "PUT",
    body: JSON.stringify({ token: trimmed }),
  });
  if (!result.ok) return { ok: false, message: message(result.status, result.error.code) };
  revalidatePath("/settings/accounts");
  return { ok: true };
}

export async function deleteQiitaToken(): Promise<ActionResult> {
  const result = await apiFetch<void>("/me/accounts/qiita", { method: "DELETE" });
  if (!result.ok) return { ok: false, message: message(result.status, result.error.code) };
  revalidatePath("/settings/accounts");
  return { ok: true };
}
