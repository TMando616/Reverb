/**
 * ログインの中継（design.md §12-1）。
 *
 * FastAPI が返した token は Cookie に入れ、**ボディには載せない**。ブラウザに
 * トークンを渡さないため（ADR-0014）。
 */

import { apiFetchAnonymous } from "@/lib/api/server";
import { setSessionCookie } from "@/lib/auth/session";

type LoginResponse = {
  token: string;
  expires_at: string;
  user: { id: number; display_name: string; is_demo: boolean };
};

export async function POST(request: Request) {
  const body = await request.json();
  const result = await apiFetchAnonymous<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(body),
  });

  if (!result.ok) {
    return Response.json({ error: result.error }, { status: result.status });
  }

  await setSessionCookie(result.data.token, result.data.expires_at);
  return Response.json({ user: result.data.user });
}
