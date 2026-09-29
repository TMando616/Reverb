/**
 * セッション Cookie の読み書き（サーバー側のみ・ADR-0014）。
 *
 * トークンは httpOnly Cookie にしか置かない。ブラウザの JavaScript から読める場所に
 * 出さないため、このファイルを Client Component から import しない。
 */

import { cookies } from "next/headers";

export const SESSION_COOKIE = "reverb_session";

/** Cookie のトークン。未ログインなら undefined。 */
export async function getSessionToken(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(SESSION_COOKIE)?.value;
}

/**
 * ログイン結果を Cookie に格納する。
 *
 * maxAge は FastAPI が返した expires_at から算出する。有効期限の定数を2箇所に
 * 持つと、サーバー側の失効と Cookie の寿命がズレて「Cookie はあるが 401」が
 * 起き続ける（design.md §12-1）。
 */
export async function setSessionCookie(token: string, expiresAt: string): Promise<void> {
  const maxAge = Math.max(0, Math.floor((Date.parse(expiresAt) - Date.now()) / 1000));
  const store = await cookies();
  store.set(SESSION_COOKIE, token, {
    httpOnly: true,
    // ローカルは http なので true にすると Cookie が保存されない（design.md §12-1）。
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge,
  });
}

export async function clearSessionCookie(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
}
