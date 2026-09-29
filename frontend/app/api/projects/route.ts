/** `/api/projects`（末尾セグメント無し）の中継。`[...path]` は1段以上に一致するため別に置く。 */

import { passthrough } from "@/lib/api/passthrough";

async function handle(request: Request) {
  return passthrough(request, ["projects"]);
}

export const GET = handle;
export const POST = handle;
