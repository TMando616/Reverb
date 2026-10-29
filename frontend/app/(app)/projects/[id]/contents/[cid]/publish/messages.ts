/**
 * 公開画面のエラー文言（publishing design.md §8-3・§12）。
 * API の `error.code`（変換は `error_code`）で分岐する。409 / 422 の意味が複数あるため。
 */

export const CONVERSION_ERRORS: Record<string, string> = {
  rate_limited: "Claude API が混み合っています。少し待ってから再実行してください",
  upstream_unavailable: "Claude API に接続できませんでした。時間をおいて再実行してください",
  misconfigured: "変換の設定に問題があります（管理者向け：API キーとモデル名を確認）",
  bad_request: "変換のリクエストが受け付けられませんでした（本文が長すぎる等）",
  truncated: "出力が長すぎて途中で切れました。本文を分けるなどしてください",
  refused: "この本文は変換できませんでした",
  invalid_output: "変換結果の形が崩れていました。再実行してください",
  interrupted: "変換が途中で止まりました。再実行してください",
  source_unavailable: "変換元を読めませんでした（権限が変わった・ネタが削除された）",
  internal_error: "予期しないエラーが起きました。再実行してください",
};

export function conversionError(code: string | null | undefined): string {
  return (code && CONVERSION_ERRORS[code]) ?? "変換に失敗しました。再実行してください";
}

/** 画面に設定画面へのリンクを添えるべきエラー。 */
export const TOKEN_ERRORS = new Set(["qiita_token_missing", "qiita_token_invalid"]);

export function requestError(status: number, code: string, message: string): string {
  switch (code) {
    case "conversion_in_progress":
      return "このチャネルの変換はすでに実行中です";
    case "unsupported_channel":
      return "このチャネルにはまだ対応していません";
    case "version_conflict":
      return "原稿が他の画面で更新されました。最新を読み込んでからやり直してください";
    case "publication_exists":
      return "すでに投稿済みです。画面を読み込み直してください";
    case "qiita_token_missing":
      return "Qiita のトークンが未登録です";
    case "qiita_token_invalid":
      return "Qiita のトークンが無効か、write_qiita の権限がありません。登録し直してください";
    case "qiita_item_missing":
      return "Qiita 側で記事が見つかりません。Qiita で消した場合は公開取消してください";
    case "invalid_draft":
      return `Qiita の条件を満たしていません（タイトル・本文・タグ1〜5個）：${message}`;
    case "qiita_rejected":
      return `Qiita が受け付けませんでした：${message}`;
    case "qiita_unavailable":
      return "Qiita に接続できませんでした。時間をおいて再実行してください";
    case "qiita_rate_limited":
      return "Qiita の利用制限に達しました。しばらく待ってから再実行してください";
    case "invalid_state_transition":
      return "この状態からは公開できません（執筆中・レビュー中のネタだけ公開できます）";
  }
  if (status === 401) return "ログインし直してください";
  if (status === 403) return "この操作の権限がありません";
  if (status === 404) return "対象が見つかりません。画面を読み込み直してください";
  if (status === 0 || status === 503) return "サーバーに接続できませんでした";
  return "操作に失敗しました";
}
