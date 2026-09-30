import { getSessionToken } from "@/lib/auth/session";

import { acceptInvitation, type AcceptState } from "./actions";
import { InviteForm } from "./InviteForm";

export default async function InvitePage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const loggedIn = (await getSessionToken()) !== undefined;

  async function action(prev: AcceptState, formData: FormData) {
    "use server";
    return acceptInvitation(token, prev, formData);
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center gap-6 px-4">
      <h1 className="text-xl font-bold">企画への招待</h1>
      <p className="text-sm text-gray-600">
        {loggedIn
          ? "ログイン中のアカウントでこの企画に参加します。"
          : "表示名とパスワードを決めて参加します。"}
      </p>
      <InviteForm loggedIn={loggedIn} action={action} />
    </main>
  );
}
