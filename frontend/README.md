# frontend — Reverb の画面と BFF

Next.js 16（App Router）/ React 19 / TypeScript / Tailwind CSS v4。
役割は **画面** と **BFF（認証の中継）** だけ。業務ロジックと認可判断は持たない（ADR-0014）。

## 起動

リポジトリのルートから、DB・API と一緒に立てる。

```bash
docker compose up          # http://localhost:3000
```

単体で動かす場合（API は別途 8000 番で起動しておく）:

```bash
npm install
npm run dev
```

## よく使うコマンド

```bash
npm run lint      # ESLint
npx next typegen  # 型の生成（LayoutProps 等）。tsc の前に必要
npx tsc --noEmit  # 型チェック
npm run build     # 本番ビルド
```

## 環境変数

| 変数 | 用途 | 既定値 |
|---|---|---|
| `API_BASE_URL` | BFF から FastAPI を呼ぶ先。**ブラウザには出ない** | `http://localhost:8000`（compose では `http://backend:8000`） |

## 構成

| パス | 役割 |
|---|---|
| `app/(auth)/` | ログイン・招待受諾 |
| `app/(app)/` | ログイン後の画面（企画一覧・企画詳細） |
| `app/api/` | BFF。Cookie ⇄ `Authorization` の載せ替えとパススルーのみ |
| `lib/api/` | FastAPI を叩くラッパと API の型 |
| `lib/auth/` | セッション Cookie の読み書き（サーバー側のみ） |

詳細な責務境界は `.kiro/steering/frontend.md`、画面の範囲は
`.kiro/specs/foundation/design.md` §12 を参照。

## 注意

- **Next.js 16 の作法は記憶で書かない。** `node_modules/next/dist/docs/` を見る（`AGENTS.md`）
- `lib/api/types.ts` は暫定の手書き。OpenAPI からの生成に置き換える（`frontend.md` §4）
