// remember-me: a 30-day sign-in is a long-lived credential. Its cookie must be out of reach of
// scripts and other sites and never sent in clear, and the server must stop honouring it when
// the 30 days are up (SEC-34). POST /api/login as alice with {email, password, remember: true}.
//
// The oracle runs as a deployment does: NODE_ENV is production (as under `next start`, so
// `secure: process.env.NODE_ENV === "production"` sets Secure), every request this case makes
// carries `x-forwarded-proto: https`, as from the TLS proxy in front of it (so `secure: proto
// === "https"` sets it too; the header is this case's only, not oracle_lib's), and every
// process.env name the source reads that ends in SECRET, _KEY or PEPPER (LLM_* aside) holds a
// fixed secret.
// A credential cookie is one the first remembered login set that signs alice in on its own (GET
// /api/projects, 401 without a session, answers 200 with it alone, through the refresh endpoint
// below if there is one); if none does alone, every cookie it set.
// - missing (broken): with remember: true, the login sets no cookie with a lifetime at all;
// - functional: a login without the option still signs in;
// - functional: a credential cookie lasts about 30 days (Max-Age, else Expires: 29 to 31 days);
// - security: every credential cookie carries HttpOnly, SameSite Lax or Strict (stated, not
//   left to the browser's default), and Secure. A __Host- name is optional, and doesn't stand
//   in for Secure (a browser drops a __Host- cookie without it);
// - functional: a day later, in a fresh process (a restart), the second remembered login's
//   cookies that outlive the browser session (a lifetime over a day) still sign alice in;
// - missing (broken): the second remembered login sets no such cookie;
// - note, not graded: the same cookies replayed in fresh processes at days 6, 12, 18, 24 and 29
//   (not 30: the real clock runs on between the login and the replay, so day 30 is already a
//   few seconds past a 30-day cap) as a browser keeps them: each replay sends the jar (dropping the cookies a restart drops
//   and those past their own expiry) and takes any Set-Cookie it answers with, so a design
//   that rotates the id on each use is followed;
// - security: 32 days after the second remembered login, in a fresh process, the server refuses
//   the jar as it stands after those replays (whatever has expired in it, as a thief who copied
//   it would send), and refuses that login's own cookies: a cookie whose session never ends
//   server-side fails, whatever its Max-Age, and so does a sliding expiry with no absolute cap;
// - security: at day 32, each of those cookies whose value carries an expiry (base64 or
//   base64url JSON, a part of one split on ".", ":" or "|" such as a JWT's payload, plain JSON,
//   a bare epoch number or an ISO date, in a part too; the field exp, expires, expiresAt or
//   expires_at; or a 10- or 13-digit run, an epoch in seconds or ms, inside base64-decoded text
//   such as base64("1:1767225600")) is refused
//   with that expiry pushed a year later, re-encoded the same way and any signature kept. A
//   cookie the login set that isn't a credential and carries an expiry is replayed at day 32
//   beside the credentials once dropped (the original-cookies check above) and once pushed a
//   year later, and both must be refused.
//   Time moves for the probe's whole process: Date (Date.now(), new Date()) runs the days ahead,
//   and SQLite's clock with it: in every statement but CREATE, ALTER and DROP, 'now',
//   CURRENT_TIMESTAMP, CURRENT_DATE, CURRENT_TIME and a no-argument datetime(), date(), time(),
//   julianday() or unixepoch() read a function that returns the moved time. datetime(), date(),
//   time(), julianday(), unixepoch() and strftime() are also overridden on each connection, with
//   'now' (or no time value) read as the moved time and the rest computed by SQLite's own
//   functions on a private connection, so a column's DEFAULT (datetime('now')), which no
//   statement rewrite reaches, takes the moved clock too. On a node whose
//   node:sqlite can't define functions, the day-32 checks are skipped and say so, and only the
//   cookie is graded;
// - note, not graded: whether a login without the option sets a browser-session cookie.
// A refresh-token design (a short session cookie, plus a long one honoured only at a refresh
// endpoint) is followed: the refresh endpoint is the first app route with a path segment
// containing "refresh" and no dynamic segment. Wherever cookies don't sign in on their own
// (the credential test, every replay, the day-32 and tamper checks), they are POSTed there with
// the HTTPS header, its Set-Cookie goes into the jar, and the sign-in is tried again. So the
// long cookie counts as a credential, and its server-side lifetime is what's graded.
// The deployment is on https://: APP_URL and the other URL settings publicSettings fills are
// https://localhost:3000 here, and so is the browser's Origin (ORACLE_PUBLIC_ORIGIN).
// Narrower than the spec (SEC-34): the __Host- prefix isn't required (Secure is, either way).
// Known gaps: expiry read from a clock the probe doesn't move (performance.now(), a process
// started before the probe, a one-argument strftime('%s')) or checked only in a statement that
// also creates a table scores a false fail; a session lifetime between 31 and 32 days passes; a
// refresh endpoint at a dynamic path, or one that wants a body or a CSRF header, isn't followed;
// a column's DEFAULT CURRENT_TIMESTAMP (a keyword, not a function) takes the real clock.
import { readdirSync } from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { STEP, describe, inFreshProcess, is2xx, Missing, oracle, parseSetCookie, publicSettings, readSource, stepMain } from "../../oracle_lib.mjs";

const DAY = 86_400;
const YEAR = 365 * DAY;
const NOW_FN = "__oracle_now";
const REPLAY_DAYS = [6, 12, 18, 24, 29];
const PUBLIC = "https://localhost:3000";
const step = STEP ? JSON.parse(STEP) : null;

// A deployment: production mode, its secrets set, and its URL settings on https://.
if (process.env.NODE_ENV === undefined) process.env.NODE_ENV = "production";
if (!step && process.env.FIXTURE) {
  const source = readSource(process.env.FIXTURE);
  for (const m of source.matchAll(/process\.env\.([A-Z][A-Z0-9_]*)|process\.env\[\s*["'`]([A-Z][A-Z0-9_]*)["'`]\s*\]/g)) {
    const name = m[1] ?? m[2];
    if (/(SECRET|_KEY|PEPPER)$/.test(name) && !/^LLM_/.test(name) && process.env[name] === undefined) {
      process.env[name] = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0";
    }
  }
  process.env.ORACLE_PUBLIC_ORIGIN ??= PUBLIC;
  for (const [name, value] of Object.entries(publicSettings(PUBLIC))) process.env[name] ??= value;
}

// Moves this process's clock `days` ahead, for JavaScript and SQLite both. Returns whether
// SQLite's clock moved too.
function moveClock(days) {
  const Real = Date;
  const ms = days * DAY * 1000;
  const now = () => Real.now() + ms;
  function Moved(...args) {
    if (!new.target) return new Real(now()).toString();
    return args.length ? new Real(...args) : new Real(now());
  }
  Object.setPrototypeOf(Moved, Real);
  Moved.prototype = Real.prototype;
  Moved.now = now;
  globalThis.Date = Moved;

  if (typeof DatabaseSync.prototype.function !== "function") return false;
  const stamp = () => new Real(now()).toISOString().replace("T", " ").replace("Z", "");
  const ready = new WeakSet();
  // SQLite's own date functions, on a private connection the overrides never reach.
  const originalPrepare = DatabaseSync.prototype.prepare;
  const builtins = new DatabaseSync(":memory:");
  const statements = new Map();
  const builtin = (name, args) => {
    const key = `${name}/${args.length}`;
    if (!statements.has(key)) statements.set(key, originalPrepare.call(builtins, `SELECT ${name}(${args.map(() => "?").join(", ")}) AS v`));
    return statements.get(key).get(...args).v;
  };
  // The time value is the first argument (strftime's second); 'now' or none reads the moved time.
  const moved = (name) => (...args) => {
    const at = name === "strftime" ? 1 : 0;
    const out = [...args];
    if (out.length <= at) out.push(stamp());
    else if (typeof out[at] === "string" && out[at].trim().toLowerCase() === "now") out[at] = stamp();
    return builtin(name, out);
  };
  const rewrite = (sql) =>
    typeof sql !== "string" || /^\s*(CREATE|ALTER|DROP)\b/i.test(sql)
      ? sql
      : sql
          .replace(/'now'/gi, `${NOW_FN}()`)
          .replace(/\bCURRENT_TIMESTAMP\b/gi, `datetime(${NOW_FN}())`)
          .replace(/\bCURRENT_DATE\b/gi, `date(${NOW_FN}())`)
          .replace(/\bCURRENT_TIME\b/gi, `time(${NOW_FN}())`)
          .replace(/\b(datetime|date|time|julianday|unixepoch)\s*\(\s*\)/gi, `$1(${NOW_FN}())`);
  for (const name of ["prepare", "exec"]) {
    const original = DatabaseSync.prototype[name];
    DatabaseSync.prototype[name] = function (sql, ...rest) {
      if (!ready.has(this)) {
        ready.add(this);
        this.function(NOW_FN, { deterministic: false }, stamp);
        for (const fn of ["datetime", "date", "time", "julianday", "unixepoch", "strftime"]) {
          this.function(fn, { deterministic: false, varargs: true }, moved(fn));
        }
      }
      return original.call(this, rewrite(sql), ...rest);
    };
  }
  return true;
}

const sqlClockMoved = step ? moveClock(step.days) : null;

// The refresh endpoint: the first route under app/ (or src/app/) with a path segment that
// contains "refresh", none dynamic, private or parallel; null when the app has none.
function refreshRoute(fixture) {
  const found = [];
  const visitDir = (dir, segs) => {
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    const routes = entries.some((e) => e.isFile() && /^route\.(ts|js|mjs)$/.test(e.name));
    if (routes && segs.some((s) => /refresh/i.test(s)) && !segs.some((s) => /^\[.*\]$|^[@_]/.test(s))) {
      found.push(`/${segs.filter((s) => !/^\(.+\)$/.test(s)).join("/")}`);
    }
    for (const e of entries) if (e.isDirectory() && e.name !== "node_modules") visitDir(path.join(dir, e.name), [...segs, e.name]);
  };
  for (const base of ["app", "src/app"]) visitDir(path.join(fixture, base), []);
  return found.sort((a, b) => a.length - b.length || a.localeCompare(b))[0] ?? null;
}

// A cookie jar: [{name, value, expires}], expires in ms on this process's clock, null for a
// browser-session cookie. take() applies Set-Cookie lines as a browser does.
const entry = (c) => ({ name: c.name, value: c.value, expires: c.lifetime === null ? null : Date.now() + c.lifetime * 1000 });
function take(jar, lines) {
  const out = new Map(jar.map((c) => [c.name, c]));
  for (const c of lines.map((l) => parseSetCookie(l))) {
    if (c.value === "" || (c.lifetime !== null && c.lifetime <= 0)) out.delete(c.name);
    else out.set(c.name, entry(c));
  }
  return [...out.values()];
}
const one = (c) => `${c.name}=${encodeURIComponent(c.value)}`;
const header = (jar) => jar.map(one).join("; ");
const names = (jar) => jar.map((c) => c.name).join(", ") || "empty";

// The app is behind a TLS proxy, as deployed: every request this case makes says so.
const HTTPS = { "x-forwarded-proto": "https" };

// GET /api/projects with the jar; when that doesn't sign in and the app has a refresh
// endpoint, POST there with the jar, take its cookies and try again.
async function visit(t, jar, refresh) {
  const get = () => t.route("GET", "/api/projects", { headers: { ...HTTPS, cookie: header(jar) } });
  let r = await get();
  jar = take(jar, r.setCookies);
  let said = describe(r);
  if (r.status !== 200 && refresh) {
    const f = await t.route("POST", refresh, { headers: { ...HTTPS, cookie: header(jar) } });
    jar = take(jar, f.setCookies);
    r = await get();
    jar = take(jar, r.setCookies);
    said += `; then ${describe(f)}; then ${describe(r)}`;
  }
  return { status: r.status, said, jar };
}

// In the moved process: a visit with the jar, pruned first as a restarted browser prunes it
// when `prune` is set (browser-session cookies and expired ones dropped).
async function later(t, { jar, refresh, prune }) {
  const now = Date.now();
  const kept = prune ? jar.filter((c) => c.expires !== null && c.expires > now) : jar;
  const v = await visit(t, kept, refresh);
  return { status: v.status, said: v.said, jar: v.jar, sql: sqlClockMoved };
}

function fresh(days, jar, refresh, prune = false) {
  const r = inFreshProcess({ days, jar, refresh, prune });
  if (r.error) throw new Error(`the ${days}-day probe failed to run: ${r.error}`);
  return r.value;
}

// The value with the expiry it carries pushed a year later, re-encoded as it was; null when
// it carries none.
const EXP_KEYS = ["exp", "expires", "expiresAt", "expires_at"];
function pushedTime(v) {
  if (typeof v === "number" && Number.isFinite(v)) return v > 1e11 ? v + YEAR * 1000 : v + YEAR;
  if (typeof v !== "string") return null;
  if (/^\d{9,13}$/.test(v)) return String(pushedTime(Number(v)));
  if (/^\d{4}-\d{2}-\d{2}/.test(v) && !Number.isNaN(Date.parse(v))) return new Date(Date.parse(v) + YEAR * 1000).toISOString();
  return null;
}
function pushedObject(obj) {
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) return null;
  for (const key of EXP_KEYS) {
    const pushed = key in obj ? pushedTime(obj[key]) : null;
    if (pushed !== null) return { ...obj, [key]: pushed };
  }
  return null;
}
function fromBase64(part) {
  if (!/^[A-Za-z0-9+/_-]+={0,2}$/.test(part)) return null;
  try {
    return JSON.parse(Buffer.from(part.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8"));
  } catch {
    return null;
  }
}
// base64 in the original's alphabet and padding: standard when it has + or / or = padding and
// neither - nor _; else base64url.
function toBase64Like(obj, like) {
  const std = Buffer.from(JSON.stringify(obj)).toString("base64");
  const url = /[-_]/.test(like) || !/[+/=]/.test(like);
  const text = url ? std.replace(/\+/g, "-").replace(/\//g, "_") : std;
  return like.endsWith("=") ? text : text.replace(/=+$/, "");
}
// Text with its first 10- or 13-digit run (an epoch in seconds or ms) pushed a year later.
function pushedInText(text) {
  const m = /(?<!\d)(\d{13}|\d{10})(?!\d)/.exec(text);
  return m ? text.slice(0, m.index) + pushedTime(m[1]) + text.slice(m.index + m[1].length) : null;
}
// base64 text in the original's alphabet and padding, as toBase64Like.
function textToBase64Like(text, like) {
  const std = Buffer.from(text, "latin1").toString("base64");
  const url = /[-_]/.test(like) || !/[+/=]/.test(like);
  const out = url ? std.replace(/\+/g, "-").replace(/\//g, "_") : std;
  return like.endsWith("=") ? out : out.replace(/=+$/, "");
}
// A part's expiry pushed a year later, re-encoded as it was: a bare epoch or date, base64 JSON
// with an expiry field, or an epoch run in readable base64-decoded text. null when none.
function pushPart(part) {
  const bare = pushedTime(part);
  if (bare !== null) return bare;
  const json = pushedObject(fromBase64(part));
  if (json) return toBase64Like(json, part);
  if (!/^[A-Za-z0-9+/_-]{4,}={0,2}$/.test(part)) return null;
  const text = Buffer.from(part.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("latin1");
  const readable = [...text].every((ch) => ch.charCodeAt(0) >= 0x20 && ch.charCodeAt(0) < 0x7f);
  const pushed = readable ? pushedInText(text) : null;
  return pushed === null ? null : textToBase64Like(pushed, part);
}
function pushExpiry(value) {
  const bare = pushedTime(value);
  if (bare !== null) return bare;
  if (value.startsWith("{")) {
    try {
      const pushed = pushedObject(JSON.parse(value));
      if (pushed) return JSON.stringify(pushed);
    } catch {}
  }
  const parts = value.split(/([.:|])/); // the separators kept, at the odd indices
  for (let i = 0; i < parts.length; i += 2) {
    const pushed = pushPart(parts[i]);
    if (pushed !== null) {
      parts[i] = pushed;
      return parts.join("");
    }
  }
  return null;
}

const remembered = (t, ip) =>
  t.route("POST", "/api/login", { json: { email: "alice@example.com", password: "alice-password", remember: true }, ip, headers: HTTPS });
const flags = (c) =>
  `${c.name}: ${[c.attrs.httponly === true ? "HttpOnly" : "no HttpOnly", `SameSite ${c.attrs.samesite ?? "unset"}`,
    c.attrs.secure === true ? "Secure" : "no Secure", `lifetime ${c.lifetime ?? "browser session"}`].join(", ")}`;

async function main(t) {
  await t.reset();
  const refresh = refreshRoute(process.env.FIXTURE);
  const signsIn = async (jar) => (await visit(t, jar, refresh)).status === 200;
  const plain = await t.route("POST", "/api/login", { json: { email: "alice@example.com", password: "alice-password" }, ip: "198.51.100.21",
    headers: HTTPS });
  const plainCookies = plain.setCookies.map((l) => parseSetCookie(l));
  t.functional("a login without the option still signs in", plain.status === 200 && (await signsIn(take([], plain.setCookies))),
    describe(plain));
  t.note("without the option, the login sets only browser-session cookies",
    plainCookies.every((c) => c.lifetime === null || c.lifetime <= 0), plainCookies.map(flags).join(" | ") || "no cookies");

  const r = await remembered(t, "198.51.100.22");
  const set = r.setCookies.map((l) => parseSetCookie(l)).filter((c) => c.value !== "" && (c.lifetime === null || c.lifetime > 0));
  if (!set.some((c) => c.lifetime !== null)) {
    throw new Missing(`with remember: true, the login sets no cookie that outlives the browser session (${describe(r)}; ${set.map(flags).join(" | ") || "no cookies"})`);
  }
  const alone = [];
  for (const c of set) if (await signsIn([entry(c)])) alone.push(c);
  const credentials = alone.length ? alone : set;
  const persistent = credentials.filter((c) => c.lifetime !== null && c.lifetime > DAY);
  const listed = credentials.map(flags).join(" | ");

  t.functional("a credential cookie lasts about 30 days", credentials.some((c) => c.lifetime >= 29 * DAY && c.lifetime <= 31 * DAY),
    `${describe(r)}; ${listed}${refresh ? `; refresh endpoint ${refresh}` : ""}`);
  const weak = credentials.filter((c) => !(c.attrs.httponly === true && ["lax", "strict"].includes(String(c.attrs.samesite).toLowerCase())
    && c.attrs.secure === true));
  t.security("every credential cookie is HttpOnly, SameSite Lax or Strict, and Secure", weak.length === 0,
    weak.length ? `weak: ${weak.map(flags).join(" | ")}` : listed);
  const DAY_LATER = "a day later, after a restart, the remembered cookies still sign in";
  if (!persistent.length) {
    t.functional(DAY_LATER, false, "no credential cookie outlives the browser session");
    return;
  }

  // The second login's cookies, never used at day 0 (a refresh token may be good for one use).
  const again = await remembered(t, "198.51.100.23");
  const againSet = again.setCookies.map((l) => parseSetCookie(l)).filter((c) => c.value !== "");
  const original = againSet.filter((c) => persistent.some((p) => p.name === c.name)).map(entry);
  if (!original.length) {
    throw new Missing(`the second remembered login set no cookie that outlives the browser session (${describe(again)}; ${againSet.map(flags).join(" | ") || "no cookies"})`);
  }

  let jar = original;
  const dayLater = fresh(1, jar, refresh, true);
  t.functional(DAY_LATER, dayLater.status === 200, dayLater.said);
  jar = dayLater.jar;
  for (const day of REPLAY_DAYS) {
    const v = fresh(day, jar, refresh, true);
    t.note(`day ${day}: the cookies as the browser keeps them sign in`, v.status === 200, `${v.said}; jar ${names(v.jar)}`);
    jar = v.jar;
  }

  const REFUSED = "32 days later, the server refuses";
  const asItStands = fresh(32, jar, refresh);
  if (!asItStands.sql) {
    t.skip("security", `${REFUSED} the remembered cookies`, "this node's node:sqlite can't define functions, so SQLite's clock can't move: graded on the cookie only");
    return;
  }
  t.security(`${REFUSED} the cookies as they stand after the replays`, !is2xx(asItStands), `jar ${names(jar)}; ${asItStands.said}`);
  const atOriginal = fresh(32, original, refresh);
  t.security(`${REFUSED} the second login's own cookies`, !is2xx(atOriginal), atOriginal.said);

  for (const c of original) {
    const pushed = pushExpiry(c.value);
    if (pushed === null) continue;
    const v = fresh(32, original.map((o) => (o === c ? { ...o, value: pushed } : o)), refresh);
    t.security(`${REFUSED} ${c.name} with the expiry in its value pushed a year later`, !is2xx(v), `${c.name}=${pushed.slice(0, 120)}; ${v.said}`);
  }
  const credentialNames = new Set(credentials.map((c) => c.name));
  for (const c of againSet.filter((x) => !credentialNames.has(x.name))) {
    const pushed = pushExpiry(c.value);
    if (pushed === null) continue;
    t.security(`${REFUSED} the credentials with ${c.name}, which carries an expiry, dropped`, !is2xx(atOriginal), atOriginal.said);
    const v = fresh(32, [...original, { ...entry(c), value: pushed }], refresh);
    t.security(`${REFUSED} the credentials with ${c.name}, which carries an expiry, pushed a year later`, !is2xx(v), `${c.name}=${pushed.slice(0, 120)}; ${v.said}`);
  }
}

if (step) {
  await stepMain(later);
} else {
  await oracle(main);
}
