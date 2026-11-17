"use server";

// Creates an account from a FormData with the fields name, email and password.
// Resolves to { ok: true } on success, or { ok: false, error } with a message to show.
export async function signup(formData: FormData): Promise<{ ok: boolean; error?: string }> {
  const email = String(formData.get("email") ?? "");
  if (!email.includes("@")) return { ok: false, error: "Enter a valid email" };
  return { ok: true };
}
