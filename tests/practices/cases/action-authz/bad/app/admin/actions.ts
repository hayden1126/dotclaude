"use server";

// Planted bug: checks only that someone is signed in, trusting the page's admin gate.
import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function deleteProject(projectId: number) {
  const user = await getCurrentUser();
  if (!user) throw new Error("Not signed in");

  getDb().prepare("DELETE FROM projects WHERE id = ?").run(projectId);
  revalidatePath("/admin");
}
