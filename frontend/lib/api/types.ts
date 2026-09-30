/**
 * API のレスポンス型。
 *
 * **暫定で手書きしている。** `frontend.md` §4 は OpenAPI からの生成を求めており、
 * 生成の仕組み（生成物のコミットと CI での差分検出）は M0 の後に入れる。
 * そのとき、このファイルは生成物に置き換える。
 */

export type ContentStatus =
  | "inbox"
  | "adopted"
  | "drafting"
  | "in_review"
  | "published"
  | "shelved";

export type Role = "owner" | "editor" | "reviewer";

export type Project = {
  id: number;
  name: string;
  role: Role;
  created_at: string;
};

export type Content = {
  id: number;
  project_id: number;
  title: string;
  body_md: string;
  status: ContentStatus;
  version: number;
  created_by: number;
  created_at: string;
  updated_at: string;
};

export type Me = {
  id: number;
  email: string;
  display_name: string;
  is_demo: boolean;
};

export type InvitationAccepted = {
  project_id: number;
  role: Role;
};

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
