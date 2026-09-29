/**
 * 現在のセッションの照会（design.md §12-1）。Cookie のトークンで /auth/me を中継する。
 */

import { apiFetch } from "@/lib/api/server";

type MeResponse = { id: number; email: string; display_name: string; is_demo: boolean };

export async function GET() {
  const result = await apiFetch<MeResponse>("/auth/me");
  if (!result.ok) {
    return Response.json({ error: result.error }, { status: result.status });
  }
  return Response.json(result.data);
}
