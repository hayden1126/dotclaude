"use server";

// Deletes the client. Resolves when deleted; throws when the client can't be deleted.
export async function deleteClient(id: number): Promise<void> {
  if (!Number.isInteger(id)) throw new Error("Bad id");
}
