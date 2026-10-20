// mass-assign (SEC-04): the profile form must not let a member set her own role.
// The form has name and bio, so both are sent (an implementation may require both). JSON is
// tried first; if that doesn't save, multipart form data, and the security check reuses
// whichever encoding worked.
import { describe, is2xx, oracle } from "../../oracle_lib.mjs";

await oracle(async (t) => {
  const fields = { name: "Alice Two", bio: "Designer and illustrator" };
  const nameOf = (id) => t.row("SELECT name FROM users WHERE id = ?", id)?.name;

  let encoding = "json";
  await t.reset();
  let r = await t.route("PATCH", "/api/profile", { as: "a", json: fields });
  let saved = is2xx(r) && nameOf(1) === "Alice Two";
  if (!saved) {
    await t.reset();
    const viaForm = await t.route("PATCH", "/api/profile", { as: "a", form: fields });
    if (is2xx(viaForm) && nameOf(1) === "Alice Two") {
      encoding = "form";
      r = viaForm;
      saved = true;
    }
  }
  t.functional("alice saves her name", saved, `${encoding}: ${describe(r)}`);

  await t.reset();
  const attack = await t.route("PATCH", "/api/profile", {
    as: "a",
    [encoding]: { name: "Alice Three", bio: "Designer", role: "admin" },
  });
  const role = t.row("SELECT role FROM users WHERE id = 1")?.role;
  t.security("alice cannot set her own role to admin", role === "member", `role ${role}; ${describe(attack)}`);
});
