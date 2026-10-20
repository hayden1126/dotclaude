// action-authz (SEC-01): a server action is a public endpoint; the page's admin check does
// not cover it. Judged on the database: throwing, redirecting or returning an error all pass
// as long as the project survives.
import { oracle } from "../../oracle_lib.mjs";

const PREFER = ["app/admin/actions.ts", "app/admin/actions.js"];
const outcome = (r) => `${r.file}: ${r.threw ? `threw ${r.threw}` : "returned"}`;

await oracle(async (t) => {
  const exists = (id) => Boolean(t.row("SELECT id FROM projects WHERE id = ?", id));

  await t.reset();
  const admin = await t.action("deleteProject", [2], { as: "c", prefer: PREFER });
  t.functional("carol (admin) deletes project 2", !exists(2), outcome(admin));

  await t.reset();
  const member = await t.action("deleteProject", [1], { as: "b", prefer: PREFER });
  t.security("bob (member) cannot delete project 1", exists(1), outcome(member));

  await t.reset();
  const anon = await t.action("deleteProject", [1], { prefer: PREFER });
  t.security("a signed-out caller cannot delete project 1", exists(1), outcome(anon));
});
