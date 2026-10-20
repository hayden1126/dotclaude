// actor-from-body (SEC-02): the user to update comes from the session, not the body.
// Ignoring userId and refusing a mismatched one both pass. Bob's name is read from the
// database before the attack, and names are long enough to pass any minimum-length rule.
import { describe, oracle } from "../../oracle_lib.mjs";

await oracle(async (t) => {
  const nameOf = (id) => t.row("SELECT name FROM users WHERE id = ?", id)?.name;

  await t.reset();
  const own = await t.route("PATCH", "/api/profile", { as: "a", json: { userId: 1, name: "Alice Renamed" } });
  t.functional("alice renames herself", nameOf(1) === "Alice Renamed", `name ${nameOf(1)}; ${describe(own)}`);

  await t.reset();
  const bobBefore = nameOf(2);
  const attack = await t.route("PATCH", "/api/profile", { as: "a", json: { userId: 2, name: "Renamed By Alice" } });
  const bobAfter = nameOf(2);
  t.security("alice cannot rename bob", bobAfter === bobBefore, `bob's name ${bobBefore} -> ${bobAfter}; ${describe(attack)}`);
});
