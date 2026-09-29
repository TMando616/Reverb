/**
 * BFF のパススルー（design.md §12-1）。
 *
 * Cookie → `Authorization: Bearer` に載せ替えて FastAPI へ流し、返ってきたものを
 * そのまま返す。**ここで業務判断をしない。** パスやボディを見て分岐を書き始めたら
 * それは越境（ADR-0014 §BFF の責務）。
 */

import { apiFetch } from "@/lib/api/server";

/** `/api/projects/1/contents` → `/projects/1/contents` の対応で中継する。 */
export async function passthrough(request: Request, segments: string[]): Promise<Response> {
  const url = new URL(request.url);
  const path = `/${segments.join("/")}${url.search}`;
  const method = request.method;
  const body = method === "GET" || method === "DELETE" ? undefined : await request.text();

  const result = await apiFetch<unknown>(path, { method, body });
  if (!result.ok) {
    return Response.json({ error: result.error }, { status: result.status });
  }
  if (result.status === 204) {
    return new Response(null, { status: 204 });
  }
  return Response.json(result.data, { status: result.status });
}
