"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";

/**
 * TanStack Query の Provider。**プッシュが届く画面（編集画面）にだけ置く**（content-pipeline design.md §9-1）。
 *
 * サーバー描画ではリクエストごとに新しいクライアントを作り、ブラウザでは1つを使い回す。
 * サーバーで使い回すと、別ユーザーのキャッシュが混ざる。
 */
let browserQueryClient: QueryClient | undefined;

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      // 初期データは Server Component から HydrationBoundary で渡す。
      // 直後にブラウザで取り直さないよう、少しの間は新鮮とみなす。
      queries: { staleTime: 60_000 },
    },
  });
}

function getQueryClient() {
  if (typeof window === "undefined") return makeQueryClient();
  browserQueryClient ??= makeQueryClient();
  return browserQueryClient;
}

export function QueryProvider({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={getQueryClient()}>{children}</QueryClientProvider>;
}
