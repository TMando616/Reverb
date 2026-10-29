"use client";

import { useState, useTransition, type FormEvent } from "react";

import { deleteQiitaToken, registerQiitaToken } from "./actions";

type Props = { registered: boolean; userName: string | null; disabled: boolean };

/**
 * Qiita トークンの登録・差し替え・削除（publishing design.md §13-1）。
 * 入力したトークンは送信後すぐに消す。登録済みでも値は表示しない（API も返さない）。
 */
export function QiitaTokenForm({ registered, userName, disabled }: Props) {
  const [token, setToken] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, startTransition] = useTransition();

  function submit(event: FormEvent) {
    event.preventDefault();
    startTransition(async () => {
      const result = await registerQiitaToken(token);
      setToken("");
      setNotice(result.ok ? "登録しました" : result.message);
    });
  }

  function remove() {
    if (!window.confirm("Qiita のトークンを削除します。Qiita への投稿・更新ができなくなります。")) return;
    startTransition(async () => {
      const result = await deleteQiitaToken();
      setNotice(result.ok ? "削除しました" : result.message);
    });
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm">
        {registered ? (
          <>
            登録済み：<span className="font-mono">@{userName}</span>
          </>
        ) : (
          "未登録"
        )}
      </p>
      <form onSubmit={submit} className="flex flex-col gap-2">
        <label htmlFor="qiita-token" className="text-sm text-gray-700">
          {registered ? "トークンを差し替える" : "アクセストークン"}
        </label>
        <input
          id="qiita-token"
          type="password"
          autoComplete="off"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          disabled={disabled || pending}
          className="rounded border border-gray-300 px-2 py-1 font-mono"
        />
        <p className="text-xs text-gray-500">
          Qiita の「設定 → アプリケーション → 個人用アクセストークン」で、
          <span className="font-mono">read_qiita</span> と
          <span className="font-mono">write_qiita</span> のスコープを付けて発行してください。
          トークンは暗号化して保存し、画面には表示しません。
        </p>
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={disabled || pending || token.trim() === ""}
            className="rounded bg-gray-900 px-3 py-1 text-sm text-white disabled:opacity-50"
          >
            {pending ? "確認中…" : registered ? "差し替える" : "登録する"}
          </button>
          {registered && (
            <button
              type="button"
              onClick={remove}
              disabled={disabled || pending}
              className="rounded border border-gray-300 px-3 py-1 text-sm disabled:opacity-50"
            >
              削除
            </button>
          )}
        </div>
      </form>
      {notice !== "" && (
        <p aria-live="polite" className="text-sm text-gray-700">
          {notice}
        </p>
      )}
    </div>
  );
}
