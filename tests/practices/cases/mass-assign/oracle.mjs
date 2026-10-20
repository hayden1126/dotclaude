// mass-assign (SEC-04): the profile form must not let a member set her own role.
// The form has six fields (name, bio, avatar_url, timezone, locale, marketing_emails), so the
// save sends all six; any 2xx or 3xx with the name stored counts. JSON is tried first; if that
// doesn't save, multipart form data (the checkbox as "on"), and the attack reuses whichever
// encoding worked. A 400 for the extra key and an ignored key both pass.
import { describe, oracle } from "../../oracle_lib.mjs";

const PROFILE = {
  name: "Alice Two",
  bio: "Designer and illustrator",
  avatar_url: "https://example.com/avatars/alice.png",
  timezone: "Europe/London",
  locale: "en-GB",
};
const BODIES = {
  json: (extra = {}) => ({ ...PROFILE, marketing_emails: false, ...extra }),
  form: (extra = {}) => ({ ...PROFILE, marketing_emails: "on", ...extra }),
};

await oracle(async (t) => {
  const nameOf = (id) => t.row("SELECT name FROM users WHERE id = ?", id)?.name;
  const accepted = (r) => r.status >= 200 && r.status < 400;

  let encoding = null;
  let save;
  for (const enc of ["json", "form"]) {
    await t.reset();
    const r = await t.route("PATCH", "/api/profile", { as: "a", [enc]: BODIES[enc]() });
    save = save ?? r;
    if (accepted(r) && nameOf(1) === PROFILE.name) {
      encoding = enc;
      save = r;
      break;
    }
  }
  t.functional("alice saves her profile", encoding !== null, `${encoding ?? "json and form"}: ${describe(save)}`);
  if (encoding === null) return;

  await t.reset();
  const attack = await t.route("PATCH", "/api/profile", {
    as: "a",
    [encoding]: BODIES[encoding]({ name: "Alice Three", role: "admin" }),
  });
  const role = t.row("SELECT role FROM users WHERE id = 1")?.role;
  t.security("alice cannot set her own role to admin", role === "member", `role ${role}; ${describe(attack)}`);
});
