import Link from "next/link";
import { redirect } from "next/navigation";

import { apiFetch, type ApiResult } from "@/lib/api/server";
import type { Me, QiitaAccount } from "@/lib/api/types";

import { QiitaTokenForm } from "./QiitaTokenForm";

/** 外部サービスのアカウント（publishing design.md §13-1）。トークンはユーザー単位で、企画に属さない。 */
export default async function AccountsPage() {
  const [me, qiita] = await Promise.all([
    apiFetch<Me>("/auth/me"),
    apiFetch<QiitaAccount>("/me/accounts/qiita"),
  ]);
  for (const result of [me, qiita] as ApiResult<unknown>[]) {
    if (!result.ok) {
      if (result.status === 401) redirect("/login");
      return (
        <main className="mx-auto flex w-full max-w-2xl flex-col gap-4 px-4 py-10">
          <p className="text-sm text-red-600">
            読み込めませんでした（{result.status}: {result.error.code}）。
          </p>
        </main>
      );
    }
  }
  if (!me.ok || !qiita.ok) return null;

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-col gap-6 px-4 py-10">
      <div className="flex flex-col gap-1">
        <Link href="/projects" className="text-sm text-gray-500 hover:underline">
          ← 企画一覧
        </Link>
        <h1 className="text-xl font-bold">外部アカウント</h1>
      </div>
      <section className="flex flex-col gap-3 rounded border border-gray-200 p-4">
        <h2 className="font-bold">Qiita</h2>
        {me.data.is_demo && (
          <p className="text-sm text-gray-600">デモアカウントではトークンを登録できません。</p>
        )}
        <QiitaTokenForm
          registered={qiita.data.registered}
          userName={qiita.data.external_user_id ?? null}
          disabled={me.data.is_demo}
        />
      </section>
    </main>
  );
}
