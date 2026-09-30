import { LoginForm } from "./LoginForm";

export default function LoginPage() {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-sm flex-col justify-center gap-6 px-4">
      <h1 className="text-xl font-bold">Reverb にログイン</h1>
      <LoginForm />
    </main>
  );
}
