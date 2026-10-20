"use server";

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function renameProject(projectId: number, name: string) {
  const user = await getCurrentUser();
  if (!user) throw new Error("Not signed in");

  const trimmed = name.trim();
  if (!trimmed || trimmed.length > 100) throw new Error("Name must be 1 to 100 characters");

  const result = getDb()
    .prepare("UPDATE projects SET name = ? WHERE id = ? AND owner_id = ?")
    .run(trimmed, projectId, user.id);
  if (result.changes === 0) throw new Error("Project not found");

  revalidatePath("/projects");
}
