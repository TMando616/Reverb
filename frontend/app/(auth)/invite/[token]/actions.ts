"use server";

import { redirect } from "next/navigation";

import { apiFetch } from "@/lib/api/server";
import type { InvitationAccepted } from "@/lib/api/types";
import { clearSessionCookie, getSessionToken } from "@/lib/auth/session";

export type AcceptState = { message: string };

export async function acceptInvitation(
  token: string,
  _prev: AcceptState,
  formData: FormData,
): Promise<AcceptState> {
  const displayName = String(formData.get("display_name") ?? "");
  const password = String(formData.get("password") ?? "");
  const loggedIn = (await getSessionToken()) !== undefined;

  // ログイン済みなら本人として受諾する。未登録の場合だけ display_name と password を送る
  // （design.md §9-1）。どちらを送るかは API の契約に合わせるだけで、判断はしない。
  const body = loggedIn ? {} : { display_name: displayName, password };

  // token は URL のセグメントとしてデコード済みで届く。そのまま埋めると
  // ..%2f や %3f で上流のパスを差し替えられる（passthrough.ts の同じ話）。
  const result = await apiFetch<InvitationAccepted>(
    `/invitations/${encodeURIComponent(token)}/accept`,
    { method: "POST", body: JSON.stringify(body) },
  );

  if (!result.ok) {
    if (result.status === 401) {
      // Cookie はあるがトークンが失効している。持っていないのと同じ扱いにしないと、
      // 入力欄が隠れたまま受諾できない状態で詰まる。
      await clearSessionCookie();
      redirect(`/invite/${token}`);
    }
    if (result.status === 404) {
      return { message: "この招待リンクは使えません（期限切れ・受諾済みの可能性があります）" };
    }
    if (result.status === 403) {
      return { message: "デモアカウントでは招待を受諾できません" };
    }
    return { message: result.error.message };
  }

  // 受諾でユーザーを作った場合はまだログインしていないので、ログイン画面へ送る。
  redirect(loggedIn ? `/projects/${result.data.project_id}` : "/login");
}
