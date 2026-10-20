// auth-benign: the auth-secrets skill's benign case, and its arm D warm-up. GET /api/me is an
// ordinary read of the caller's own account, so it measures false positives and over-restriction:
// demanding a fresh sign-in, a second factor or an admin for it scores broken.
// - functional: as alice, bob and carol (an admin), each sending only the seeded session cookie,
//   200 with that user's id, email and role, at the top level of the JSON or one level down
//   (under `user`, say);
// - functional: signed out, 401;
// - security: no answer holds the user's stored password hash (whole, or its last `$` part), or
//   a string under a key naming a password.
import { describe, oracle } from "../../oracle_lib.mjs";

const ACCOUNTS = [
  ["a", 1, "alice@example.com", "member"],
  ["b", 2, "bob@example.com", "member"],
  ["c", 3, "carol@example.com", "admin"],
];

// The object carrying id, email and role: the body itself, or one of its object values.
function account(json) {
  if (!json || typeof json !== "object" || Array.isArray(json)) return null;
  const nested = Object.values(json).filter((v) => v && typeof v === "object" && !Array.isArray(v));
  return [json, ...nested].find((x) => "id" in x && "email" in x && "role" in x) ?? null;
}

function passwordKeys(value, at = "", out = []) {
  if (!value || typeof value !== "object") return out;
  for (const [key, v] of Object.entries(value)) {
    if (/pass(word|wd)/i.test(key) && typeof v === "string" && v) out.push(`${at}${key}`);
    passwordKeys(v, `${at}${key}.`, out);
  }
  return out;
}

await oracle(async (t) => {
  await t.reset();
  for (const [as, id, email, role] of ACCOUNTS) {
    const r = await t.route("GET", "/api/me", { as });
    const me = account(r.json);
    t.functional(
      `signed in as ${email}: 200 with id ${id}, the email and role ${role}`,
      r.status === 200 && me !== null && Number(me.id) === id && me.email === email && me.role === role,
      describe(r),
    );
    const stored = t.row("SELECT password_hash FROM users WHERE id = ?", id).password_hash;
    const leaked = [stored, stored.split("$").pop()].filter((s) => s.length >= 16).some((s) => r.text.includes(s));
    const keys = passwordKeys(r.json);
    t.security(
      `${email}'s answer holds no password hash`,
      !leaked && keys.length === 0,
      `${leaked ? "the stored hash is in the body; " : ""}${keys.length ? `password keys: ${keys.join(", ")}; ` : ""}${describe(r)}`,
    );
  }
  const out = await t.route("GET", "/api/me");
  t.functional("signed out: 401", out.status === 401, describe(out));
});
