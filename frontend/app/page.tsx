import { redirect } from "next/navigation";

/** 入口は企画一覧。未ログインなら /projects 側が /login へ送る。 */
export default function Home() {
  redirect("/projects");
}
