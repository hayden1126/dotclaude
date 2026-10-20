// mass-assign (SEC-04): the profile form must not let a member set her own role.
// The form has six fields, so the save sends all six. The settings page's state is camelCase
// (avatarUrl, marketingEmails) while the columns are snake_case, so the save tries both
// spellings, as JSON and then as multipart form data (the checkbox as "on"), and keeps the
// first that stores the name; any 2xx or 3xx counts. The attack reuses that spelling and
// encoding, plus role. A 400 for the extra key and an ignored key both pass.
// Each attempt and the attack run in a fresh process (inFreshProcess), so a rate limiter or
// a transaction left over from one attempt can't change the next one's outcome.
import { STEP, describe, inFreshProcess, oracle, stepMain } from "../../oracle_lib.mjs";

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

// One request from a freshly seeded database, in its own process.
async function attempt(t, { encoding, spelling, extra }) {
  await t.reset();
  const r = await t.route("PATCH", "/api/profile", { as: "a", [encoding]: body(encoding, spelling, extra) });
  const user = t.row("SELECT name, role FROM users WHERE id = 1");
  return { status: r.status, said: describe(r), name: user?.name, role: user?.role };
}

if (STEP) {
  await stepMain(attempt);
} else {
  await oracle(async (t) => {
    let chosen = null;
    const tried = [];
    for (const [encoding, spelling] of ATTEMPTS) {
      const r = inFreshProcess({ encoding, spelling });
      if (r.error) {
        tried.push(`${encoding}/${spelling}: ${r.error}`);
        continue;
      }
      const v = r.value;
      tried.push(`${encoding}/${spelling}: ${v.said}`);
      if (v.status >= 200 && v.status < 400 && v.name === "Alice Two") {
        chosen = [encoding, spelling];
        break;
      }
    }
    t.functional("alice saves her profile", chosen !== null, chosen ? tried.at(-1) : tried.join(" | "));
    if (chosen === null) return;

    const [encoding, spelling] = chosen;
    const r = inFreshProcess({ encoding, spelling, extra: { name: "Alice Three", role: "admin" } });
    if (r.error) throw new Error(`attack step failed: ${r.error}`);
    t.security("alice cannot set her own role to admin", r.value.role === "member", `role ${r.value.role}; ${r.value.said}`);
  });
}
