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
    // 401 の文面は API 側に寄せる（列挙対策で「どちらが違うか」を出さない・design.md §4-2）。
    return { message: "メールアドレスかパスワードが違います" };
  }

  await setSessionCookie(result.data.token, result.data.expires_at);
  redirect("/projects");
}
