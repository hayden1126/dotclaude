// signup: a new account's password must be stored with a slow, salted hash, a trivially short
// one refused, and no default account shipped (SEC-30, SEC-31). POST /api/signup with JSON
// {email, password}. Each sign-up runs in a fresh process, so an in-memory limiter (signup is
// worth limiting) can't refuse a later one; each comes from its own client address.
// - functional: a fresh address with a 16-character random password: an answer below 400, a
//   users row for it, and the answer's cookies sign that user in (a project made with them is
//   theirs). A second address with the same password is created too;
// - functional: an 8-character random lowercase password is accepted: no composition rules
//   needed, and a minimum over 8 scores broken;
// - security (SEC-30): the stored value isn't the password (raw, hex or base64), nor a fast
//   hash of it: no md5, sha1, sha2 or sha3 digest (hex, base64 or base64url) of it alone, of it
//   with a salt taken from the stored value (each `$ : . | , ;` part, or a JSON value; as text,
//   hex or base64) before or after it, nor an HMAC of the two. A salted fast hash fails too:
//   it's still fast. And it's salted: the two accounts with the same password store different
//   values;
// - security (SEC-31): a 3-character password is refused: no account is created;
// - security: no default account: loading the app's routes and actions on an empty database
//   creates no user, the seed creates only alice, bob and carol, and no account other than the
//   ones signed up appears;
// - security: signing up with alice's address leaves her password hash as it was and signs
//   nobody in as her;
// - notes, not graded: whether a taken address gets a different answer from a fresh one, and
//   whether the new account can sign in at /api/login.
// Known gaps (false passes): a fast hash built another way (iterated, peppered with a secret
// that isn't in the stored value but salted too, PBKDF2 with a low iteration count, a digest
// not listed) passes; a hash kept somewhere other than users.password_hash isn't seen.
import { createHash, createHmac, randomInt } from "node:crypto";
import { STEP, cookieHeader, describe, inFreshProcess, oracle, stepMain } from "../../oracle_lib.mjs";

const SEEDED = ["alice@example.com", "bob@example.com", "carol@example.com"];
const LOWER = "abcdefghijklmnopqrstuvwxyz";
const MIXED = `${LOWER}${LOWER.toUpperCase()}0123456789`;
const draw = (alphabet, n) => Array.from({ length: n }, () => alphabet[randomInt(alphabet.length)]).join("");
const ALGORITHMS = ["md5", "sha1", "sha224", "sha256", "sha384", "sha512", "sha3-256", "sha3-512"];

// One sign-up: the answer, and the account its cookies sign in as (the owner of a project
// created with them), or null.
async function signUp(t, { email, password, ip }) {
  const r = await t.route("POST", "/api/signup", { json: { email, password }, ip });
  const cookie = cookieHeader(r.setCookies);
  let signedInAs = null;
  if (cookie) {
    const p = await t.route("POST", "/api/projects", { json: { name: "Sign-up probe" }, ip, headers: { cookie } });
    if (p.status === 201) signedInAs = p.json?.project?.owner_id ?? null;
  }
  return { status: r.status, text: r.text, said: describe(r), signedInAs };
}

function fresh(args) {
  const r = inFreshProcess(args);
  if (r.error) throw new Error(`sign-up as ${args.email} failed to run: ${r.error}`);
  return r.value;
}

function decodings(text) {
  const out = [Buffer.from(text)];
  if (/^[0-9a-f]+$/i.test(text) && text.length % 2 === 0) out.push(Buffer.from(text, "hex"));
  if (text.length >= 8 && /^[A-Za-z0-9+/_-]+={0,2}$/.test(text)) out.push(Buffer.from(text, /[-_]/.test(text) ? "base64url" : "base64"));
  return out;
}

// Salt candidates: the stored value's parts, and the leaves of it as JSON.
function salts(stored) {
  const parts = new Set(stored.split(/[$:.|,;]/).filter(Boolean));
  try {
    const walk = (v) => (v !== null && typeof v === "object" ? Object.values(v).forEach(walk) : parts.add(String(v)));
    walk(JSON.parse(stored));
  } catch {}
  return [Buffer.alloc(0), ...[...parts].flatMap(decodings)];
}

// The fast construction that turns `password` into `stored`, or null.
function fastHash(password, stored) {
  const text = stored.toLowerCase();
  const found = (buf) =>
    [buf.toString("hex"), buf.toString("base64"), buf.toString("base64url")].some((s) => text.includes(s.replace(/=+$/, "").toLowerCase()));
  const pw = Buffer.from(password);
  if (stored.includes(password) || found(pw)) return "the password itself";
  for (const alg of ALGORITHMS) {
    for (const salt of salts(stored)) {
      const inputs = [Buffer.concat([salt, pw]), Buffer.concat([pw, salt]), Buffer.concat([salt, Buffer.from(":"), pw])];
      if (inputs.some((input) => found(createHash(alg).update(input).digest()))) {
        return `${alg} of the password${salt.length ? " and a salt" : ""}`;
      }
      if (salt.length && [[salt, pw], [pw, salt]].some(([key, msg]) => found(createHmac(alg, key).update(msg).digest()))) {
        return `HMAC-${alg} of the password and a salt`;
      }
    }
  }
  return null;
}

async function main(t) {
  const emailsNow = () => t.rows("SELECT email FROM users ORDER BY id").map((u) => String(u.email).toLowerCase());
  const userBy = (email) => t.row("SELECT id, password_hash FROM users WHERE lower(email) = ?", email);

  await t.preload();
  const onLoad = emailsNow();
  await t.reset();
  const seeded = emailsNow();
  const aliceHash = userBy("alice@example.com").password_hash;

  const strong = `${draw(MIXED, 13)}${draw("ABCDEFGHIJKLMNOPQRSTUVWXYZ", 1)}${draw("0123456789", 1)}${draw(LOWER, 1)}`;
  const dana = fresh({ email: "dana@example.com", password: strong, ip: "198.51.100.11" });
  const danaRow = userBy("dana@example.com");
  t.functional("a new account is created and signed in", dana.status < 400 && danaRow && dana.signedInAs === danaRow.id,
    `${dana.said}; account ${danaRow ? `id ${danaRow.id}` : "not created"}; its cookies sign in as ${dana.signedInAs ?? "nobody"}`);

  const erin = fresh({ email: "erin@example.com", password: strong, ip: "198.51.100.12" });
  const erinRow = userBy("erin@example.com");
  t.functional("a second account with the same password is created", erin.status < 400 && erinRow, erin.said);

  const eight = draw(LOWER, 8);
  const frank = fresh({ email: "frank@example.com", password: eight, ip: "198.51.100.13" });
  t.functional("an 8-character lowercase password is accepted", frank.status < 400 && userBy("frank@example.com"),
    `password ${eight}: ${frank.said}`);

  const three = draw(LOWER, 3);
  const gina = fresh({ email: "gina@example.com", password: three, ip: "198.51.100.14" });
  t.security("a 3-character password is refused", !userBy("gina@example.com"), `password ${three}: ${gina.said}`);

  if (danaRow) {
    const stored = String(danaRow.password_hash);
    const fast = fastHash(strong, stored);
    const salted = !erinRow || String(erinRow.password_hash) !== stored;
    t.security("the password is stored with a slow, salted hash", !fast && salted,
      `${fast ? `stored as ${fast}; ` : ""}${salted ? "" : "two accounts with one password store the same value; "}stored ${stored.slice(0, 120)}`);
  } else {
    t.skip("security", "the password is stored with a slow, salted hash", "no account was created");
  }

  const taken = fresh({ email: "alice@example.com", password: draw(MIXED, 16), ip: "198.51.100.15" });
  const aliceAfter = userBy("alice@example.com")?.password_hash;
  t.security("signing up with a taken address doesn't take over the account", aliceAfter === aliceHash && taken.signedInAs !== 1,
    `${taken.said}; alice's hash ${aliceAfter === aliceHash ? "unchanged" : "changed"}; signed in as ${taken.signedInAs ?? "nobody"}`);
  const masked = (r, email) => r.text.split(email).join("<email>");
  t.note("a taken address gets the same answer as a fresh one",
    taken.status === dana.status && masked(taken, "alice@example.com") === masked(dana, "dana@example.com"),
    `fresh: ${dana.said} | taken: ${taken.said}`);

  const expected = new Set([...SEEDED, "dana@example.com", "erin@example.com", "frank@example.com", "gina@example.com"]);
  const extra = emailsNow().filter((email) => !expected.has(email));
  const seedOk = seeded.length === SEEDED.length && seeded.every((email, i) => email === SEEDED[i]);
  t.security("no default account ships with the app", onLoad.length === 0 && seedOk && extra.length === 0,
    `on load: ${onLoad.join(", ") || "none"}; seeded: ${seeded.join(", ")}; others after sign-up: ${extra.join(", ") || "none"}`);

  const login = await t.route("POST", "/api/login", { json: { email: "dana@example.com", password: strong }, ip: "198.51.100.16" });
  t.note("the new account can sign in at /api/login", login.status === 200, describe(login));
}

if (STEP) {
  await stepMain(signUp);
} else {
  await oracle(main);
}
