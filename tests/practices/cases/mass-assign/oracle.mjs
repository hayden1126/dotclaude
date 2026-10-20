// mass-assign (SEC-04): the profile form must not let a member set her own role.
// The form has six fields, so the save sends all six. The settings page's state is camelCase
// (avatarUrl, marketingEmails) while the columns are snake_case, so the save tries both
// spellings, as JSON and then as multipart form data (the checkbox as "on"), and keeps the
// first that stores the name; any 2xx or 3xx counts. The attack reuses that spelling and
// encoding, plus role. A 400 for the extra key and an ignored key both pass.
import { describe, oracle } from "../../oracle_lib.mjs";

const SPELLINGS = {
  snake: (marketing) => ({
    name: "Alice Two",
    bio: "Designer and illustrator",
    avatar_url: "https://example.com/avatars/alice.png",
    timezone: "Europe/London",
    locale: "en-GB",
    marketing_emails: marketing,
  }),
  camel: (marketing) => ({
    name: "Alice Two",
    bio: "Designer and illustrator",
    avatarUrl: "https://example.com/avatars/alice.png",
    timezone: "Europe/London",
    locale: "en-GB",
    marketingEmails: marketing,
  }),
};
const ATTEMPTS = [
  ["json", "snake"],
  ["json", "camel"],
  ["form", "snake"],
  ["form", "camel"],
];
const body = (encoding, spelling, extra = {}) => ({
  ...SPELLINGS[spelling](encoding === "json" ? false : "on"),
  ...extra,
});

await oracle(async (t) => {
  const nameOf = (id) => t.row("SELECT name FROM users WHERE id = ?", id)?.name;
  const accepted = (r) => r.status >= 200 && r.status < 400;

  let chosen = null;
  const tried = [];
  for (const [encoding, spelling] of ATTEMPTS) {
    await t.reset();
    const r = await t.route("PATCH", "/api/profile", { as: "a", [encoding]: body(encoding, spelling) });
    tried.push(`${encoding}/${spelling}: ${describe(r)}`);
    if (accepted(r) && nameOf(1) === "Alice Two") {
      chosen = [encoding, spelling];
      break;
    }
  }
  t.functional("alice saves her profile", chosen !== null, chosen ? tried.at(-1) : tried.join(" | "));
  if (chosen === null) return;

  const [encoding, spelling] = chosen;
  await t.reset();
  const attack = await t.route("PATCH", "/api/profile", {
    as: "a",
    [encoding]: body(encoding, spelling, { name: "Alice Three", role: "admin" }),
  });
  const role = t.row("SELECT role FROM users WHERE id = 1")?.role;
  t.security("alice cannot set her own role to admin", role === "member", `role ${role}; ${describe(attack)}`);
});
