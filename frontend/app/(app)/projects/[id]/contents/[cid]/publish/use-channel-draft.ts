"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";

import { bffFetch } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type { ChannelDraft, ChannelView } from "@/lib/api/types";

import { requestError } from "./messages";

/** 原稿の編集中バッファ。**クライアント状態**で、キャッシュには書き込まない（frontend.md §2）。 */
export type DraftBuffer = { title: string; body: string; tags: string };

const toBuffer = (draft: ChannelDraft): DraftBuffer => ({
  title: draft.title,
  body: draft.body,
  tags: draft.tags.join(", "),
});

const same = (a: DraftBuffer, b: DraftBuffer) =>
  a.title === b.title && a.body === b.body && a.tags === b.tags;

/** 「Python, FastAPI」→ ["Python", "FastAPI"]。読点と全角カンマも区切りにする。 */
export function parseTags(text: string): string[] {
  return [
    ...new Set(
      text
        .split(/[,、，]/)
        .map((t) => t.trim())
        .filter((t) => t !== ""),
    ),
  ];
}

export type SaveResult = { ok: true; version: number } | { ok: false; message: string };

/**
 * 原稿の保存（publishing design.md §13-2）。自動保存はしない（手動＋⌘S）。
 *
 * - `expected_version` は「このバッファが基づいている版」を送る（content-pipeline と同じ考え方）
 * - サーバーの原稿が進んでいて（変換結果の反映・別タブ）、こちらに未保存の変更が無ければ追従する。
 *   未保存の変更があるときは上書きせず、保存したときに 409 で知らせる
 */
export function useChannelDraft(
  projectId: number,
  contentId: number,
  channel: string,
  draft: ChannelDraft | null,
) {
  const queryClient = useQueryClient();
  const key = queryKeys.channel(projectId, contentId, channel);
  const [buffer, setBuffer] = useState<DraftBuffer | null>(draft ? toBuffer(draft) : null);
  const [saved, setSaved] = useState<DraftBuffer | null>(draft ? toBuffer(draft) : null);
  const [saving, setSaving] = useState(false);
  const [conflict, setConflict] = useState(false);
  // このバッファが基づいている原稿の版。進めるのは自分の保存・置き換え・追従だけ。
  const [baseVersion, setBaseVersion] = useState(draft?.version ?? 0);

  const dirty = buffer !== null && saved !== null && !same(buffer, saved);

  // サーバーの原稿が変わったら（初回の変換・置き換え・別タブの保存）、手元が未保存でなければ追従する。
  // Effect ではなく描画中に合わせる（react.dev「You Might Not Need an Effect」）。
  if (draft !== null && draft.version !== baseVersion && !dirty) {
    setBaseVersion(draft.version);
    setBuffer(toBuffer(draft));
    setSaved(toBuffer(draft));
    setConflict(false);
  }

  const save = useCallback(async (): Promise<SaveResult> => {
    if (buffer === null) return { ok: false, message: "原稿がまだありません" };
    if (!dirty) return { ok: true, version: baseVersion };
    setSaving(true);
    const sending = buffer;
    const result = await bffFetch<ChannelDraft>(
      `/projects/${projectId}/contents/${contentId}/channels/${channel}/draft`,
      {
        method: "PUT",
        body: JSON.stringify({
          title: sending.title,
          body: sending.body,
          tags: parseTags(sending.tags),
          expected_version: baseVersion,
        }),
      },
    );
    setSaving(false);
    if (!result.ok) {
      if (result.code === "version_conflict") setConflict(true);
      return { ok: false, message: requestError(result.status, result.code, result.message) };
    }
    setBaseVersion(result.data.version);
    setSaved(sending);
    queryClient.setQueryData<ChannelView>(key, (view) =>
      view ? { ...view, draft: result.data } : view,
    );
    return { ok: true, version: result.data.version };
  }, [buffer, dirty, baseVersion, projectId, contentId, channel, queryClient, key]);

  /** 409 のあと、手元を捨ててサーバーの原稿を読み込む。 */
  const reload = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: key });
    const view = queryClient.getQueryData<ChannelView>(key);
    if (view?.draft) {
      setBaseVersion(view.draft.version);
      setBuffer(toBuffer(view.draft));
      setSaved(toBuffer(view.draft));
    }
    setConflict(false);
  }, [queryClient, key]);

  /** 置き換え（apply）の結果を手元に入れる。 */
  const adopt = useCallback((next: ChannelDraft) => {
    setBaseVersion(next.version);
    setBuffer(toBuffer(next));
    setSaved(toBuffer(next));
    setConflict(false);
  }, []);

  return { buffer, setBuffer, dirty, saving, conflict, save, reload, adopt, baseVersion };
}
