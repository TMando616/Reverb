# ADR-0016: Markdown エディタとプレビュー

- **日付**: 2026-10-10
- **ステータス**: 採用（`content-pipeline` の実装完了で確定・2026-10-18）

## 背景

`tech.md` / `requirements-overview.md` §13 / `frontend.md` §7 に「CodeMirror 6 / tiptap」で未決のまま残っていた。
`content-pipeline` の C5（エディタと編集画面）に入る前に決める必要がある。

前提は2つ。

1. **エディタは自作しない**（tech.md）。設計対象ではないので、既製品を組み込むだけにする
2. **本文の正は `contents.body_md`（Markdown 文字列）**。リビジョン（C7）も、Qiita への公開（`publishing`）も、
   MCP 経由で Claude Code が読み書きするのも、すべてこの文字列。**エディタを通すと Markdown が書き換わる**、は許容できない

## 選択肢

| 案 | 編集の対象 | 利点 | 欠点 |
|---|---|---|---|
| **A. CodeMirror 6** | Markdown のテキストそのもの | **保存される文字列 ＝ 画面で打った文字列。** 往復で崩れようがない。シンタックスハイライト・キーバインド・undo が揃っている | 見た目は「ハイライト付きのテキストエディタ」。プレビューは別に用意する |
| B. tiptap（ProseMirror） | ProseMirror のドキュメントツリー | WYSIWYG で、書きながら見た目が分かる | **Markdown は入出力時の変換になる。** 表・脚注・Qiita 独自記法・空行の数・リストの記号（`-` / `*`）などが往復で正規化される。MCP で外から書いた本文を開いただけで差分が出る |
| C. textarea ＋ 自前の補助 | テキスト | 依存ゼロ | 行番号・ハイライト・undo の粒度・IME 周りを自分で面倒を見ることになる。**実質的に自作** |

### プレビュー

| 案 | 内容 |
|---|---|
| **a. react-markdown ＋ remark-gfm** | Markdown → React 要素。**生の HTML を解釈しない**のが既定。`javascript:` などの危険な URL も既定で無効化する |
| b. marked / markdown-it → `dangerouslySetInnerHTML` ＋ DOMPurify | HTML 文字列を作ってから消毒する。消毒の設定を間違えると即 XSS |

## 決定

**エディタは CodeMirror 6 を採用する**（`@codemirror/lang-markdown`。React への組み込みは薄いラッパ `@uiw/react-codemirror` を使う）。

**プレビューは react-markdown ＋ remark-gfm。生の HTML は描画しない**（`rehype-raw` を入れない）。

## 理由

### CodeMirror 6 を選ぶ理由

1. **`body_md` が往復で崩れない。** 本文を書き換える入口が3つ（ブラウザ / MCP / 将来の取り込み）あり、
   どこから書いても同じ文字列が残ることが、リビジョン（C7）と楽観ロック（C6）の前提になる。
   tiptap では「開いて閉じただけで本文が変わり、`version` が進み、リビジョンが1件増える」が起き得る
2. **Qiita の記法をそのまま書ける。** 公開先の Qiita は Markdown を受け取る。WYSIWYG のモデルに無い記法
   （`:::note` 等）は tiptap では拡張を書かないと消える。拡張を書くのは自作に近づく
3. **後続スペックの「行」の概念と相性が良い。** `collaboration` のレビューコメントは行アンカー、
   編集ロックはセクション単位（見出し単位）。どちらも「Markdown テキストの行」で数えるのが素直で、
   CodeMirror は行・範囲の API を素で持っている

tiptap を却下する理由は 1・2。WYSIWYG の書き心地は魅力だが、**正の形式が Markdown である以上、
変換を挟む構造そのものが合わない。** textarea（C）を却下するのは、自作の線を越えるため。

### プレビューの理由

本文は reviewer / demo も閲覧する（C8）。**他人が書いた本文を自分のブラウザで描画する**ので、XSS は現実の脅威になる。

- b は「HTML を作る → 消毒する」の2段で、消毒の設定ミスがそのまま穴になる
- a は**最初から HTML 文字列を経由しない**。生の HTML はテキストとしてエスケープされ、危険な URL は除去される

Qiita は一部の HTML タグを許すので、プレビューと Qiita の実表示が完全には一致しない。
**プレビューは「体裁と分量の確認」用で、Qiita の見た目の再現ではない**と割り切る（`publishing` のチャネル変換で再評価する）。

## 影響

- `tech.md` のスタック表と `frontend.md` §7、`requirements-overview.md` §13 のエディタ項目を確定に更新する
- CodeMirror はブラウザの DOM を前提にするので、**エディタのコンポーネントはクライアント側だけで描画する**
  （`next/dynamic` の `ssr: false`。Client Component の中で使う必要がある — `frontend/node_modules/next/dist/docs/01-app/02-guides/lazy-loading.md`）
- 文字数の表示（C8）はエディタではなく、アプリ側で `body_md` から数える（エディタを差し替えても数え方が変わらないように）
- **`rehype-raw` を入れない**ことをレビューの観点に加える。入れた瞬間に C8 のサニタイズ要件を満たさなくなる

## 覆すとしたら

「書いている途中の見た目」が要件として強くなった場合（例：Markdown を知らない共同編集者が増える）。
その場合でも正の形式は Markdown のまま、**往復で崩れないことをテストで担保できるかどうか**を採用条件にする。
