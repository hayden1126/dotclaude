// remember-me: a 30-day sign-in is a long-lived credential. Its cookie must be out of reach of
// scripts and other sites and never sent in clear, and the server must stop honouring it when
// the 30 days are up (SEC-34). POST /api/login as alice with {email, password, remember: true}.
//
// The oracle runs as a deployment does: NODE_ENV is production (as under `next start`, so
// `secure: process.env.NODE_ENV === "production"` sets Secure), and every process.env name the
// source reads that ends in SECRET, _KEY or PEPPER (LLM_* aside) holds a fixed secret.
// A credential cookie is one the login set that signs alice in on its own (GET /api/projects,
// 401 without a session, answers 200 with it alone); if none does alone, every cookie it set.
// - missing (broken): with remember: true, the login sets no cookie with a lifetime at all;
// - functional: a login without the option still signs in;
// - functional: a credential cookie lasts about 30 days (Max-Age, else Expires: 29 to 31 days);
// - functional: a day later, in a fresh process (a restart), the cookies that outlive the
//   browser session (a lifetime over a day) still sign alice in;
// - security: every credential cookie carries HttpOnly, SameSite Lax or Strict (stated, not
//   left to the browser's default), and Secure, or a __Host- name;
// - security: 32 days after a fresh remembered login, in a fresh process, the server refuses
//   those cookies: a cookie whose session never ends server-side fails, whatever its Max-Age.
//   Time moves for the probe's whole process: Date (Date.now(), new Date()) runs 32 days ahead,
//   and SQLite's clock with it: in every statement but CREATE, ALTER and DROP, 'now',
//   CURRENT_TIMESTAMP, CURRENT_DATE, CURRENT_TIME and a no-argument datetime(), date(), time(),
//   julianday() or unixepoch() read a function that returns the moved time. On a node whose
//   node:sqlite can't define functions, this check is skipped and says so, and only the cookie
//   is graded;
// - note, not graded: whether a login without the option sets a browser-session cookie.
// Known gaps: expiry read from a clock the probe doesn't move (performance.now(), a process
// started before the probe, a one-argument strftime('%s')) or checked only in a statement that
// also creates a table scores a false fail; a session lifetime between 31 and 32 days passes.
import { DatabaseSync } from "node:sqlite";
import { STEP, cookieHeader, describe, inFreshProcess, is2xx, Missing, oracle, parseSetCookie, readSource, stepMain } from "../../oracle_lib.mjs";

const DAY = 86_400;
const NOW_FN = "__oracle_now";
const step = STEP ? JSON.parse(STEP) : null;

// A deployment: production mode, and its secrets set.
if (process.env.NODE_ENV === undefined) process.env.NODE_ENV = "production";
if (!step && process.env.FIXTURE) {
  const source = readSource(process.env.FIXTURE);
  for (const m of source.matchAll(/process\.env\.([A-Z][A-Z0-9_]*)|process\.env\[\s*["'`]([A-Z][A-Z0-9_]*)["'`]\s*\]/g)) {
    const name = m[1] ?? m[2];
    if (/(SECRET|_KEY|PEPPER)$/.test(name) && !/^LLM_/.test(name) && process.env[name] === undefined) {
      process.env[name] = "0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0";
    }
  }
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
      }
      return original.call(this, rewrite(sql), ...rest);
    };
  }
  return true;
}

const sqlClockMoved = step ? moveClock(step.days) : null;

// In the moved process: GET /api/projects with these cookies.
async function later(t, { cookie }) {
  const r = await t.route("GET", "/api/projects", { headers: { cookie } });
  return { status: r.status, said: describe(r), sql: sqlClockMoved };
}

function fresh(days, cookie) {
  const r = inFreshProcess({ days, cookie });
  if (r.error) throw new Error(`the ${days}-day probe failed to run: ${r.error}`);
  return r.value;
}

const remembered = (t, ip) =>
  t.route("POST", "/api/login", { json: { email: "alice@example.com", password: "alice-password", remember: true }, ip });
const signsIn = async (t, cookie) => (await t.route("GET", "/api/projects", { headers: { cookie } })).status === 200;
const one = (c) => `${c.name}=${encodeURIComponent(c.value)}`;
const flags = (c) =>
  `${c.name}: ${[c.attrs.httponly === true ? "HttpOnly" : "no HttpOnly", `SameSite ${c.attrs.samesite ?? "unset"}`,
    c.attrs.secure === true ? "Secure" : "no Secure", `lifetime ${c.lifetime ?? "browser session"}`].join(", ")}`;

async function main(t) {
  await t.reset();
  const plain = await t.route("POST", "/api/login", { json: { email: "alice@example.com", password: "alice-password" }, ip: "198.51.100.21" });
  const plainCookies = plain.setCookies.map((l) => parseSetCookie(l));
  t.functional("a login without the option still signs in", plain.status === 200 && (await signsIn(t, cookieHeader(plain.setCookies))),
    describe(plain));
  t.note("without the option, the login sets only browser-session cookies",
    plainCookies.every((c) => c.lifetime === null || c.lifetime <= 0), plainCookies.map(flags).join(" | ") || "no cookies");

  const r = await remembered(t, "198.51.100.22");
  const set = r.setCookies.map((l) => parseSetCookie(l)).filter((c) => c.value !== "" && (c.lifetime === null || c.lifetime > 0));
  if (!set.some((c) => c.lifetime !== null)) {
    throw new Missing(`with remember: true, the login sets no cookie that outlives the browser session (${describe(r)}; ${set.map(flags).join(" | ") || "no cookies"})`);
  }
  const alone = [];
  for (const c of set) if (await signsIn(t, one(c))) alone.push(c);
  const credentials = alone.length ? alone : set;
  const persistent = credentials.filter((c) => c.lifetime !== null && c.lifetime > DAY);
  const listed = credentials.map(flags).join(" | ");

  t.functional("a credential cookie lasts about 30 days", credentials.some((c) => c.lifetime >= 29 * DAY && c.lifetime <= 31 * DAY),
    `${describe(r)}; ${listed}`);
  const header = persistent.map(one).join("; ");
  const dayLater = header ? fresh(1, header) : { status: 0, said: "no credential cookie outlives the browser session" };
  t.functional("a day later, after a restart, the remembered cookies still sign in", dayLater.status === 200, dayLater.said);

  const weak = credentials.filter((c) => !(c.attrs.httponly === true && ["lax", "strict"].includes(String(c.attrs.samesite).toLowerCase())
    && (c.attrs.secure === true || c.name.startsWith("__Host-"))));
  t.security("every credential cookie is HttpOnly, SameSite Lax or Strict, and Secure", weak.length === 0,
    weak.length ? `weak: ${weak.map(flags).join(" | ")}` : listed);

  const again = await remembered(t, "198.51.100.23");
  const againHeader = again.setCookies.map((l) => parseSetCookie(l))
    .filter((c) => persistent.some((p) => p.name === c.name) && c.value !== "").map(one).join("; ");
  const expired = againHeader ? fresh(32, againHeader) : null;
  if (!expired) {
    t.skip("security", "32 days later, the server refuses the remembered cookies", "the second remembered login set no such cookies");
  } else if (!expired.sql) {
    t.skip("security", "32 days later, the server refuses the remembered cookies", "this node's node:sqlite can't define functions, so SQLite's clock can't move: graded on the cookie only");
  } else {
    t.security("32 days later, the server refuses the remembered cookies", !is2xx(expired), expired.said);
  }
}

if (step) {
  await stepMain(later);
} else {
  await oracle(main);
}
