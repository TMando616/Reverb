/**
 * ログアウトの中継（design.md §12-1）。
 *
 * Cookie の削除とサーバー側トークンの失効の両方が要る（ADR-0014 §影響）。
 * FastAPI 側が失敗しても Cookie は消す：手元に使えないトークンを残さない。
 */

import { apiFetch } from "@/lib/api/server";
import { clearSessionCookie } from "@/lib/auth/session";

export async function POST() {
  const result = await apiFetch<undefined>("/auth/logout", { method: "POST" });
  await clearSessionCookie();
  return new Response(null, { status: result.ok ? 204 : result.status });
}
