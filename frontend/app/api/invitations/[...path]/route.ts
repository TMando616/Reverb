/** `/api/invitations/**` を FastAPI の `/invitations/**` へ中継する（design.md §12-1）。 */

import { passthrough } from "@/lib/api/passthrough";

type Context = { params: Promise<{ path: string[] }> };

async function handle(request: Request, { params }: Context) {
  const { path } = await params;
  return passthrough(request, ["invitations", ...path]);
}

export const POST = handle;
