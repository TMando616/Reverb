/**
 * ブラウザから BFF（`/api/**`）を叩くラッパ。編集画面の TanStack Query が使う
 * （content-pipeline design.md §9-1）。
 *
 * ブラウザから FastAPI を直接叩かない（ADR-0014）。トークンは httpOnly Cookie にあり、
 * ここからは見えない。BFF が Cookie を Authorization に載せ替えて中継する。
 */

export type ClientResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; code: string; message: string };

export async function bffFetch<T>(path: string, init: RequestInit = {}): Promise<ClientResult<T>> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    return { ok: false, status: 0, code: "network_error", message: "通信できませんでした" };
  }
  if (response.status === 204) {
    return { ok: true, status: 204, data: undefined as T };
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (body as { error?: { code: string; message: string } } | null)?.error;
    return {
      ok: false,
      status: response.status,
      code: error?.code ?? "internal_error",
      message: error?.message ?? "unexpected error",
    };
  }
  return { ok: true, status: response.status, data: body as T };
}
