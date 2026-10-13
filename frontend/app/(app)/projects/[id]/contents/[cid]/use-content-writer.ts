"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { bffFetch } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import type { Content, ContentStatus, Tag } from "@/lib/api/types";

/** 編集中バッファ。**クライアント状態**で、サーバー状態のキャッシュには書き込まない（frontend.md §2）。 */
export type Draft = { title: string; body: string };

/** 保存の段階。表示用の5状態（design.md §9-6）は、これと「未保存の変更があるか」から作る。 */
type Phase = "idle" | "saving" | "error" | "conflict";
export type SaveStatus = "saved" | "dirty" | "saving" | "error" | "conflict";

/** 入力が止まってから自動保存するまで（design.md §9-6：リビジョンが細切れにならない長さ）。 */
const AUTOSAVE_DELAY_MS = 5_000;
/** 保存に失敗したとき、1回だけ自動で再試行するまで。 */
const RETRY_DELAY_MS = 10_000;

const sameDraft = (a: Draft, b: Draft) => a.title === b.title && a.body === b.body;

/** 復元の結果。キャンセルと失敗を区別する（キャンセルでダイアログを閉じない）。 */
export type RestoreOutcome = { restored: true } | { restored: false; message: string | null };

/**
 * 編集画面の書き込みをすべて受け持つ（content-pipeline design.md §9-5〜9-7）。
 *
 * - **書き込みは1本の列に並べる。** 本文の保存・元ノート・状態遷移・復元はどれも `version` を進める。
 *   並行して送ると、自分の2つ目が自分の1つ目に負けて 409 になる
 * - **`expected_version` は「このバッファが基づいている版」（baseVersion）を送る。** キャッシュの
 *   `version` は使わない。M2 でプッシュがキャッシュを進めたとき、それを使うと他人の更新を
 *   上書きしてしまい、競合を検出できなくなる。baseVersion を進めるのは自分の書き込みだけ
 * - タグの付け替えは `version` を進めない（design.md §4）ので、列にも baseVersion にも関わらない
 */
export function useContentWriter(projectId: number, initial: Content) {
  const queryClient = useQueryClient();
  const key = queryKeys.content(projectId, initial.id);
  const path = `/projects/${projectId}/contents/${initial.id}`;

  const [draft, setDraft] = useState<Draft>({ title: initial.title, body: initial.body_md });
  const [saved, setSaved] = useState<Draft>({ title: initial.title, body: initial.body_md });
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState("");
  const [savedAt, setSavedAt] = useState<string | null>(null);

  const draftRef = useRef(draft);
  const savedRef = useRef(saved);
  const baseVersion = useRef(initial.version);
  const conflicted = useRef(false);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  // タグの PUT は version に関わらないので本文の列とは別に、ただし順番どおりに送る
  const tagQueue = useRef<Promise<unknown>>(Promise.resolve());
  const tagRequest = useRef(0);
  const autosaveTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const retried = useRef(false);
  // 再試行タイマーから save を呼ぶための参照（save の定義の中から自分自身を参照しない）。
  const saveRef = useRef<() => Promise<void>>(() => Promise.resolve());

  useEffect(() => {
    draftRef.current = draft;
  });

  const enqueue = useCallback(<T>(task: () => Promise<T>): Promise<T> => {
    const run = queue.current.then(task, task);
    queue.current = run.catch(() => undefined);
    return run;
  }, []);

  /** version を確かめた自分の書き込みの結果だけを反映する（baseVersion を進めてよいのはここだけ）。 */
  const accept = useCallback(
    (content: Content) => {
      baseVersion.current = content.version;
      queryClient.setQueryData(key, content);
      void queryClient.invalidateQueries({ queryKey: queryKeys.revisions(projectId, content.id) });
    },
    // key は projectId / initial.id から決まる
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queryClient, projectId, initial.id],
  );

  const markConflict = useCallback(() => {
    conflicted.current = true;
    clearTimeout(autosaveTimer.current);
    clearTimeout(retryTimer.current);
    setPhase("conflict");
  }, []);

  const save = useCallback(
    (): Promise<void> =>
      enqueue(async () => {
        if (conflicted.current) return;
        const sending = draftRef.current;
        if (sameDraft(sending, savedRef.current)) return;
        if (sending.title.trim() === "") {
          setPhase("error");
          setMessage("タイトルが空なので保存できません");
          return;
        }
        setPhase("saving");
        const result = await bffFetch<Content>(path, {
          method: "PATCH",
          body: JSON.stringify({
            title: sending.title,
            body_md: sending.body,
            expected_version: baseVersion.current,
          }),
        });
        if (result.ok) {
          savedRef.current = sending;
          setSaved(sending);
          accept(result.data);
          setSavedAt(result.data.updated_at);
          setPhase("idle");
          setMessage("");
          retried.current = false;
          return;
        }
        if (result.status === 409) {
          markConflict();
          return;
        }
        setPhase("error");
        setMessage(
          result.status === 403
            ? "保存する権限がありません"
            : result.status === 422
              ? "長すぎるか、形式が正しくありません"
              : "保存できませんでした",
        );
        if (!retried.current) {
          retried.current = true;
          retryTimer.current = setTimeout(() => void saveRef.current(), RETRY_DELAY_MS);
        }
      }),
    [enqueue, path, accept, markConflict],
  );

  useEffect(() => {
    saveRef.current = save;
  }, [save]);

  // 入力が止まってから 5 秒で保存する。変更のたびにタイマーを掛け直す。
  useEffect(() => {
    if (conflicted.current || sameDraft(draft, saved)) return;
    clearTimeout(autosaveTimer.current);
    autosaveTimer.current = setTimeout(() => void save(), AUTOSAVE_DELAY_MS);
    return () => clearTimeout(autosaveTimer.current);
  }, [draft, saved, save]);

  useEffect(
    () => () => {
      clearTimeout(autosaveTimer.current);
      clearTimeout(retryTimer.current);
    },
    [],
  );

  const saveNow = useCallback(() => {
    clearTimeout(autosaveTimer.current);
    retried.current = false;
    return save();
  }, [save]);

  /**
   * 元ノートのパス。`version` を進めるので列に並べる（design.md §4）。
   * 成功したらサーバーが正規化した値（`\` → `/`）を返し、入力欄をそれに合わせてもらう。
   */
  const saveSourceNotePath = useCallback(
    (value: string | null): Promise<{ ok: true; value: string | null } | { ok: false; message: string }> =>
      enqueue(async () => {
        if (conflicted.current) return { ok: false, message: "他の画面で更新されたため保存できません" };
        const result = await bffFetch<Content>(path, {
          method: "PATCH",
          body: JSON.stringify({ source_note_path: value, expected_version: baseVersion.current }),
        });
        if (result.ok) {
          accept(result.data);
          return { ok: true, value: result.data.source_note_path };
        }
        if (result.status === 409) {
          markConflict();
          return { ok: false, message: "他の画面で更新されました" };
        }
        return {
          ok: false,
          message:
            result.status === 422
              ? "Vault からの相対パスで入力してください（.. や絶対パスは使えません）"
              : "保存できませんでした",
        };
      }),
    [enqueue, path, accept, markConflict],
  );

  /** 状態遷移。これも `version` を進める。 */
  const transition = useCallback(
    (to: ContentStatus): Promise<string | null> =>
      enqueue(async () => {
        if (conflicted.current) return "他の画面で更新されたため変更できません";
        const result = await bffFetch<Content>(`${path}/transition`, {
          method: "POST",
          body: JSON.stringify({ to, expected_version: baseVersion.current }),
        });
        if (result.ok) {
          accept(result.data);
          return null;
        }
        if (result.status === 409) {
          markConflict();
          return "他の画面で更新されました";
        }
        return result.status === 422 ? "その状態へは進められません" : "変更できませんでした";
      }),
    [enqueue, path, accept, markConflict],
  );

  /**
   * タグの付け替え。`version` を進めないので、キャッシュの `tags` だけを差し替える。
   * 選択はレスポンスを待たずにキャッシュへ入れる。待つと、続けてチェックしたときに
   * 古い集合から次の PUT を組み立ててしまい、先に付けたタグが外れる。
   */
  const setTags = useCallback(
    (tags: Tag[]): Promise<string | null> => {
      queryClient.setQueryData<Content>(key, (old) => (old ? { ...old, tags } : old));
      const request = ++tagRequest.current;
      const run = tagQueue.current.then(async () => {
        const result = await bffFetch<Content>(`${path}/tags`, {
          method: "PUT",
          body: JSON.stringify({ tag_ids: tags.map((t) => t.id) }),
        });
        // 後続の PUT が控えていれば、その選択を画面に残す（最後の1件がサーバーの最終状態になる）
        const latest = request === tagRequest.current;
        if (!result.ok) {
          // 楽観的に入れた選択を、サーバーの実際の状態で上書きする
          if (latest) void queryClient.invalidateQueries({ queryKey: key });
          return result.code === "invalid_tag"
            ? "使えないタグが含まれています。画面を読み込み直してください"
            : "タグを保存できませんでした";
        }
        const saved: Tag[] = result.data.tags;
        if (latest) queryClient.setQueryData<Content>(key, (old) => (old ? { ...old, tags: saved } : old));
        return null;
      });
      tagQueue.current = run.catch(() => undefined);
      return run;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [queryClient, path],
  );

  /**
   * 版を復元する（design.md §9-7）。復元はサーバーの最新を書き換えるので、
   * 未保存の変更があれば先に保存するか確かめる。
   */
  const restore = useCallback(
    async (revisionNo: number): Promise<RestoreOutcome> => {
      const fail = (message: string | null): RestoreOutcome => ({ restored: false, message });
      if (!sameDraft(draftRef.current, savedRef.current)) {
        if (!window.confirm("未保存の変更があります。先に保存してから戻しますか？")) return fail(null);
        await saveNow();
        if (conflicted.current) return fail("他の画面で更新されたため戻せません");
        // 保存に失敗した（通信エラー・タイトルが空など）まま戻すと、残したかった編集が消える
        if (!sameDraft(draftRef.current, savedRef.current)) {
          return fail("未保存の変更を保存できなかったため、戻していません");
        }
      }
      return enqueue(async (): Promise<RestoreOutcome> => {
        if (conflicted.current) return fail("他の画面で更新されたため戻せません");
        const result = await bffFetch<Content>(`${path}/revisions/${revisionNo}/restore`, {
          method: "POST",
          body: JSON.stringify({ expected_version: baseVersion.current }),
        });
        if (!result.ok) {
          if (result.status === 409) {
            markConflict();
            return fail("他の画面で更新されました");
          }
          return fail("戻せませんでした");
        }
        const restored = { title: result.data.title, body: result.data.body_md };
        savedRef.current = restored;
        setSaved(restored);
        setDraft(restored);
        accept(result.data);
        setSavedAt(result.data.updated_at);
        // 直前の保存失敗の表示と、控えている再試行を片付ける（バッファはもう保存済み）
        clearTimeout(retryTimer.current);
        retried.current = false;
        setPhase("idle");
        setMessage("");
        return { restored: true };
      });
    },
    [enqueue, path, accept, markConflict, saveNow],
  );

  /** 競合時の [最新を読み込む]：自分の編集を捨ててサーバーの最新に合わせる。 */
  const reloadLatest = useCallback(async (): Promise<Content | null> => {
    const result = await bffFetch<Content>(path);
    if (!result.ok) return null;
    const latest = { title: result.data.title, body: result.data.body_md };
    conflicted.current = false;
    savedRef.current = latest;
    setSaved(latest);
    setDraft(latest);
    accept(result.data);
    setPhase("idle");
    setMessage("");
    return result.data;
  }, [path, accept]);

  const dirty = !sameDraft(draft, saved);
  const status: SaveStatus =
    phase === "conflict"
      ? "conflict"
      : phase === "saving"
        ? "saving"
        : phase === "error"
          ? "error"
          : dirty
            ? "dirty"
            : "saved";

  return {
    draft,
    setDraft,
    status,
    dirty,
    message,
    savedAt,
    saveNow,
    saveSourceNotePath,
    transition,
    setTags,
    restore,
    reloadLatest,
  };
}
