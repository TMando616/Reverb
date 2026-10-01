"use server";

import { redirect } from "next/navigation";

import { apiFetchAnonymous } from "@/lib/api/server";
import { setSessionCookie } from "@/lib/auth/session";

export type LoginState = { message: string };

type LoginResponse = { token: string; expires_at: string };

export async function login(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");

  const result = await apiFetchAnonymous<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

  if (!result.ok) {
    // 401 は「どちらが違うか」を出さない（列挙対策・design.md §4-2）。それ以外は
    // 資格情報の問題ではないので、正しいパスワードを打ち直させない文面にする。
    return {
      message:
        result.status === 401
          ? "メールアドレスかパスワードが違います"
          : "ログインできませんでした。時間をおいて試してください",
    };
  }

  const stored = await setSessionCookie(result.data.token, result.data.expires_at);
  if (!stored) {
    return { message: "ログインできませんでした。時間をおいて試してください" };
  }
  redirect("/projects");
}
