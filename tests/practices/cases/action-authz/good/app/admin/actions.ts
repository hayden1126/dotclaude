"use server";

// Secure: the action checks the admin role itself.
import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { getDb } from "@/lib/db";

export async function deleteProject(projectId: number) {
  const user = await getCurrentUser();
  if (!user || user.role !== "admin") throw new Error("Forbidden");

  getDb().prepare("DELETE FROM projects WHERE id = ?").run(projectId);
  revalidatePath("/admin");
}
