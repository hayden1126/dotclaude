import { getDb } from "@/lib/db";
import { hashPassword } from "@/lib/password";

// Demo data used in development and by the tests.
export function resetDb(): void {
  const db = getDb();
  db.exec("DELETE FROM invoices; DELETE FROM projects; DELETE FROM sessions; DELETE FROM users;");

  const addUser = db.prepare(
    `INSERT INTO users (id, email, name, bio, avatar_url, timezone, locale, marketing_emails, role, password_hash)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  );
  addUser.run(1, "alice@example.com", "Alice Moreau", "Freelance designer", null, "Europe/Paris", "fr-FR", 1, "member", hashPassword("alice-password"));
  addUser.run(2, "bob@example.com", "Bob Okafor", "Photographer", null, "Africa/Lagos", "en-GB", 0, "member", hashPassword("bob-password"));
  addUser.run(3, "carol@example.com", "Carol Lindqvist", "Runs Ledgerly support", null, "Europe/Stockholm", "sv-SE", 0, "admin", hashPassword("carol-password"));

  const addSession = db.prepare("INSERT INTO sessions (token, user_id) VALUES (?, ?)");
  addSession.run("tok-a", 1);
  addSession.run("tok-b", 2);
  addSession.run("tok-c", 3);

  const addProject = db.prepare("INSERT INTO projects (id, owner_id, name) VALUES (?, ?, ?)");
  addProject.run(1, 1, "Brand refresh");
  addProject.run(2, 2, "Wedding shoot");

  const addInvoice = db.prepare(
    "INSERT INTO invoices (id, owner_id, project_id, number, amount_cents, status) VALUES (?, ?, ?, ?, ?, ?)",
  );
  addInvoice.run(1, 1, 1, "INV-1001", 123456, "sent");
  addInvoice.run(2, 2, 2, "INV-1002", 777, "draft");
}
