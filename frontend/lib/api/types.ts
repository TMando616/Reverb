/**
 * 画面が使う API の型。
 *
 * **中身は OpenAPI からの生成物（`types/api.ts`）から引く。手で型を書かない**（frontend.md §4）。
 * ここに置くのは、画面側で使う短い別名と、日本語ラベル・遷移表のような表示用の定数だけ。
 *
 * API を変えたら：`backend` で `uv run python -m app.export_openapi ../frontend/openapi.json`
 * → `npm run gen:api`。CI は両方の差分を検出して落とす。
 */

import type { components } from "@/types/api";

type Schemas = components["schemas"];

export type ContentStatus = Schemas["ContentStatus"];
export type Role = Schemas["Role"];
export type RevisionKind = Schemas["RevisionKind"];

export type Project = Schemas["ProjectOut"];
export type Content = Schemas["ContentOut"];
/** 一覧の行。API は本文を返さない（body_md は単体取得で引く）。 */
export type ContentSummary = Schemas["ContentListItem"];
export type Tag = Schemas["TagOut"];
export type TagWithUsage = Schemas["TagWithUsageOut"];
export type RevisionSummary = Schemas["RevisionSummaryOut"];
export type Revision = Schemas["RevisionOut"];
export type Member = Schemas["MemberOut"];
export type Me = Schemas["MeResponse"];
export type InvitationAccepted = Schemas["InvitationAcceptOut"];

// publishing
export type Channel = Schemas["ChannelOut"];
export type ChannelCode = Schemas["ChannelCode"];
export type ChannelView = Schemas["ChannelViewOut"];
export type ChannelDraft = Schemas["ChannelDraftOut"];
export type ConversionJob = Schemas["ConversionJobOut"];
export type JobStatus = Schemas["JobStatus"];
export type Publication = Schemas["PublicationOut"];
export type PublishedContent = Schemas["PublishedContentOut"];
export type QiitaAccount = Schemas["QiitaAccountOut"];
export type Visibility = Schemas["Visibility"];

/** 状態の日本語ラベル。識別子は英語、表示は日本語（design.md §3-2）。 */
export const STATUS_LABELS: Record<ContentStatus, string> = {
  inbox: "ネタ",
  adopted: "採用",
  drafting: "執筆中",
  in_review: "レビュー中",
  published: "公開済み",
  shelved: "棚上げ",
};

/** 遷移表（design.md §8-1）。ここは表示の出し分け用で、可否の判定は API 側が正典。 */
export const ALLOWED_TRANSITIONS: Record<ContentStatus, ContentStatus[]> = {
  inbox: ["adopted", "shelved"],
  adopted: ["inbox", "drafting", "shelved"],
  drafting: ["adopted", "in_review", "shelved"],
  in_review: ["drafting", "shelved"],
  published: [],
  shelved: ["inbox"],
};

/** カンバンの列の並び。状態遷移の流れに沿わせる（content-pipeline C2）。 */
export const STATUS_ORDER: ContentStatus[] = [
  "inbox",
  "adopted",
  "drafting",
  "in_review",
  "published",
  "shelved",
];

/**
 * 書き込み系の操作を画面に出すか。**UX のための出し分けで、防御は API の 403**（frontend.md §1）。
 * owner / editor で、かつ demo でないとき。
 */
export function canWrite(role: Role, isDemo: boolean): boolean {
  return !isDemo && (role === "owner" || role === "editor");
}

/**
 * 公開・更新・公開取消のボタンを出すか。owner で、かつ demo でないとき（publishing design.md §5）。
 * これも UX のための出し分けで、防御は API の 403。
 */
export function canPublish(role: Role, isDemo: boolean): boolean {
  return !isDemo && role === "owner";
}

export const VISIBILITY_LABELS: Record<Visibility, string> = {
  private: "限定共有",
  public: "一般公開",
};

/** 日時の表示。サーバー描画とブラウザでタイムゾーンがズレないよう固定する。 */
const DATE_TIME = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export function formatDateTime(iso: string): string {
  return DATE_TIME.format(new Date(iso));
}
