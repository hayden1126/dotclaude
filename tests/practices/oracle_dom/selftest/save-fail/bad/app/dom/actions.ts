"use server";
// practices-allow: SEC-01 a selftest stand-in: oracle_dom replaces this module with a proxy, so its body never runs

export async function saveNote(text: string): Promise<void> {
  if (!text) throw new Error("empty");
}
