"use server";
// practices-allow: SEC-01 a selftest stand-in: oracle_dom replaces this module with a proxy, so its body never runs

export async function archiveEverything(_: unknown, __?: unknown): Promise<{ error: string | null }> {
  return { error: null };
}
