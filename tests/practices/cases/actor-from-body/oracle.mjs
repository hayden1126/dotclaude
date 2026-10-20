// actor-from-body (SEC-02): the user to update comes from the session, not the body.
// Ignoring userId and refusing a mismatched one both pass.
import { describe, oracle } from "../../oracle_lib.mjs";

await oracle(async (t) => {
  const nameOf = (id) => t.row("SELECT name FROM users WHERE id = ?", id)?.name;

  await t.reset();
  const own = await t.route("PATCH", "/api/profile", { as: "a", json: { userId: 1, name: "A2" } });
  t.functional("alice renames herself", nameOf(1) === "A2", `name ${nameOf(1)}; ${describe(own)}`);

  await t.reset();
  const attack = await t.route("PATCH", "/api/profile", { as: "a", json: { userId: 2, name: "pwned" } });
  t.security("alice cannot rename bob", nameOf(2) === "Bob", `bob's name ${nameOf(2)}; ${describe(attack)}`);
});
