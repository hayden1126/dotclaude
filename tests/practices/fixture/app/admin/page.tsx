import { notFound } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { getDb, type Project } from "@/lib/db";

type ProjectRow = Project & { owner_email: string };

export default async function AdminPage() {
  const user = await getCurrentUser();
  if (!user || user.role !== "admin") notFound();

  const projects = getDb()
    .prepare(
      `SELECT p.id, p.owner_id, p.name, p.created_at, u.email AS owner_email
         FROM projects p JOIN users u ON u.id = p.owner_id
        ORDER BY p.id`,
    )
    .all() as unknown as ProjectRow[];

  return (
    <main>
      <h1>Admin</h1>
      <h2>All projects</h2>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Name</th>
            <th>Owner</th>
            <th>Created</th>
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => (
            <tr key={project.id}>
              <td>{project.id}</td>
              <td>{project.name}</td>
              <td>{project.owner_email}</td>
              <td>{project.created_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
