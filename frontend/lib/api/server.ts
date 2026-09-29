/**
 * FastAPI を叩くサーバー側専用のラッパ。
 *
 * ここは中継だけを行う（ADR-0014）。業務ルールと認可判断は持たない ── 認可は
 * FastAPI の Service 層の1箇所で判定される（ADR-0009）。
 */

import { getSessionToken } from "@/lib/auth/session";

/** ブラウザには出ない値。コンテナ内では http://backend:8000 を渡す。 */
const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export type ApiError = { error: { code: string; message: string } };

/** FastAPI のレスポンスをそのまま持ち回るための最小の型。 */
export type ApiResult<T> =
  | { ok: true; status: number; data: T }
  | { ok: false; status: number; error: ApiError["error"] };

async function request<T>(
  path: string,
  init: RequestInit & { token?: string | undefined } = {},
): Promise<ApiResult<T>> {
  const { token, headers, ...rest } = init;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...rest,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    // 認証付きの読み取りをキャッシュに載せない。既定でもキャッシュされないが、
    // 取り違えると他人のデータを配ることになるので明示する。
    cache: "no-store",
  });

  const status = response.status;
  if (status === 204) {
    return { ok: true, status, data: undefined as T };
  }

  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = (body as ApiError | null)?.error ?? {
      code: "internal_error",
      message: "unexpected error",
    };
    return { ok: false, status, error };
  }
  return { ok: true, status, data: body as T };
}

/** Cookie のトークンを Authorization に載せ替えて叩く（ログイン済みの経路）。 */
export async function apiFetch<T>(path: string, init: RequestInit = {}): Promise<ApiResult<T>> {
  return request<T>(path, { ...init, token: await getSessionToken() });
}

/** トークンを付けずに叩く（ログイン・招待受諾の一部）。 */
export async function apiFetchAnonymous<T>(
  path: string,
  init: RequestInit = {},
): Promise<ApiResult<T>> {
  return request<T>(path, init);
}
