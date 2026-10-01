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
  const text = method === "GET" || method === "DELETE" ? "" : await request.text();
  // 空ボディに Content-Type: application/json を付けて送ると FastAPI 側で無関係な
  // 422 になるので、中身があるときだけ送り、種類は受け取ったものをそのまま使う。
  const body = text === "" ? undefined : text;
  const contentType = request.headers.get("Content-Type");
  const headers: Record<string, string> = {};
  if (body !== undefined && contentType !== null) {
    headers["Content-Type"] = contentType;
  }

  const result = await apiFetch<unknown>(path, { method, body, headers });
  if (!result.ok) {
    return Response.json({ error: result.error }, { status: result.status });
  }
  if (result.status === 204) {
    return new Response(null, { status: 204 });
  }
  return Response.json(result.data, { status: result.status });
}
