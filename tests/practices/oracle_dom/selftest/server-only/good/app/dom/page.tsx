import { readSecret } from "@/lib/secret";

// An async server component reaching server-only code: the browser can't run it.
export default async function SecretPage() {
  const secret = await readSecret();
  return <p>{secret.length}</p>;
}
