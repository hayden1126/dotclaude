"use server";
// practices-allow: SEC-01 a selftest stand-in: oracle_dom replaces this module with a proxy, so its body never runs

export async function subscribe(formData: FormData): Promise<{ ok: boolean }> {
  return { ok: Boolean(formData.get("email")) };
}
