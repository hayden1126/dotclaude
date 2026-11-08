import { cookies } from "next/headers";

export default async function Account() {
  const store = await cookies();
  return <p>{store.get("session")?.value ?? "signed out"}</p>;
}
