/** `/api/projects/**` を FastAPI の `/projects/**` へ中継する（design.md §12-1）。 */

import { passthrough } from "@/lib/api/passthrough";

type Context = { params: Promise<{ path: string[] }> };

async function handle(request: Request, { params }: Context) {
  const { path } = await params;
  return passthrough(request, ["projects", ...path]);
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const DELETE = handle;
