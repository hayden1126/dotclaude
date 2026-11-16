import { getCurrentUser } from "@/lib/auth";

// A server page on the fixture's own auth helper, which reads next/headers.
export default async function AccountPage() {
  const user = await getCurrentUser();
  return <p>{user ? user.name : "signed out"}</p>;
}
