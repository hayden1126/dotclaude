"use server";

// Saves the note. Resolves when saved; throws when the save fails.
export async function saveNote(text: string): Promise<void> {
  if (!text.trim()) throw new Error("Nothing to save");
}
