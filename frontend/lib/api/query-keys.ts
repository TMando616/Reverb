/**
 * TanStack Query のキー（content-pipeline design.md §9-5）。
 * サーバーの初期データ（HydrationBoundary）とブラウザ側で同じキーを使うため、1箇所に置く。
 * M2 で WebSocket から届く更新も、このキーのキャッシュへ流し込む（frontend.md §2）。
 */
export const queryKeys = {
  content: (projectId: number, contentId: number) => ["content", projectId, contentId] as const,
  revisions: (projectId: number, contentId: number) => ["revisions", projectId, contentId] as const,
  revision: (projectId: number, contentId: number, revisionNo: number) =>
    ["revision", projectId, contentId, revisionNo] as const,
  /** 公開画面のまとめ（publishing design.md §13-2）。M2 でジョブ進捗の SSE をここへ流し込む。 */
  channel: (projectId: number, contentId: number, channel: string) =>
    ["channel", projectId, contentId, channel] as const,
};
