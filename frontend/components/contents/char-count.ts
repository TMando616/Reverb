/**
 * 文字数の数え方（content-pipeline design.md §8）：
 * `body_md` の原文を、改行を除いて書記素（見た目の1文字）単位で数える。
 * Markdown 記法・コードブロックも含める。絵文字や結合文字を1文字と数えるため
 * `String.length` ではなく `Intl.Segmenter` を使う。
 */
const segmenter = new Intl.Segmenter("ja", { granularity: "grapheme" });

export function countChars(markdown: string): number {
  let count = 0;
  for (const { segment } of segmenter.segment(markdown.replace(/\r?\n/g, ""))) {
    if (segment !== "") count++;
  }
  return count;
}

/** 画面に出す数え方の説明（C8「画面上で分かるように」）。 */
export const CHAR_COUNT_NOTE = "記法込み・改行除く";
