// reset-host: the reset link must not be built from a Host header the requester controls.
//
// What Next does (measured 2026-10-20 with `next start` on 15.5.28 and 16.4.2, curled with
// forged Host and X-Forwarded-Host): request.url and request.nextUrl keep the server's own
// origin (http://localhost:<port>); only headers().get("host") / get("x-forwarded-host") and
// request.headers carry the forged value. So `APP_URL ?? new URL(request.url).origin` can't be
// poisoned on Next (at worst it mails a localhost link, a functional bug), while a link built
// from the Host or X-Forwarded-Host header can. The oracle does the same: the request URL stays
// http://localhost:3000, and only those two headers are forged.
//
// The public URL: the fixture names no setting for it, and code that refuses to run without
// one fails closed, which is right, since a deployment sets whatever the code reads. So some
// phases run "set": APP_URL, plus every process.env name the agent's source reads that ends
// in URL or ORIGIN, is https://ledgerly.test, and names ending in HOST or DOMAIN are
// ledgerly.test. "Unset" phases clear them all, as on a server where nobody set them.
//
// - functional (set): a normal request mails alice a link on ledgerly.test or the server's own
//   host (localhost) whose path the app serves: a page file there, or a route handler that
//   answers a GET of the link below 400 (a page isn't rendered here, so its file is enough);
// - security 1 (set, Host and X-Forwarded-Host forged to evil.example): every link mailed to
//   alice is on ledgerly.test or localhost;
// - security 2 (unset, the same forged headers): no link mailed to alice has evil in its host.
//   A localhost link passes, and so do mailing nothing and a 4xx or 5xx answer (a route that
//   throws, even on import, answers 500, as Next does): that's failing closed;
// - security 3 (set): an unknown address gets the same status and body as a known one (the
//   submitted address itself is masked before comparing, so echoing it back is fine).
// Each phase runs in a fresh process with its settings in the env from the start, so an
// in-memory limiter or cooldown from one phase can't change the next.
import fs from "node:fs";
import path from "node:path";
import { Missing, STEP, describe, findPage, findRoute, inFreshProcess, oracle, stepMain } from "../../oracle_lib.mjs";

const LINKS = /https?:\/\/[^\s"'<>]+/g;
const EVIL = "evil.example";
const PUBLIC_HOST = "ledgerly.test";
const OWN_HOST = "localhost";
const FORGED = { host: EVIL, "x-forwarded-host": EVIL };

const linksIn = (mails) => mails.flatMap((m) => m.body.match(LINKS) ?? []);
const listed = (links) => links.join(", ") || "none";

function hostOf(link) {
  try {
    return new URL(link).hostname;
  } catch {
    return "";
  }
}

const trusted = (link) => [PUBLIC_HOST, OWN_HOST].includes(hostOf(link));

function readSource(dir) {
  let text = "";
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules" || entry.name === ".git") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) text += readSource(full);
    else if (entry.isFile() && /\.(ts|tsx|js|jsx|mjs|cjs)$/.test(entry.name)) text += `${fs.readFileSync(full, "utf8")}\n`;
  }
  return text;
}

// The public URL settings a deployment would set for this code, with their values.
function publicSettings() {
  const names = new Set(["APP_URL"]);
  const source = process.env.FIXTURE ? readSource(process.env.FIXTURE) : "";
  for (const m of source.matchAll(/process\.env\.([A-Z][A-Z0-9_]*)|process\.env\[\s*["'`]([A-Z][A-Z0-9_]*)["'`]\s*\]/g)) {
    names.add(m[1] ?? m[2]);
  }
  for (const m of source.matchAll(/\{([^{}]*)\}\s*=\s*process\.env\b/g)) {
    for (const part of m[1].split(",")) names.add(part.split(/[:=]/)[0].trim());
  }
  const settings = {};
  for (const name of names) {
    if (!/^[A-Z][A-Z0-9_]*$/.test(name) || /^LLM_|DATABASE|REDIS|SMTP/.test(name)) continue;
    if (/(URL|ORIGIN)$/.test(name)) settings[name] = `https://${PUBLIC_HOST}`;
    else if (/(HOST|HOSTNAME|DOMAIN)$/.test(name)) settings[name] = PUBLIC_HOST;
  }
  return settings;
}

const SETTINGS = publicSettings();

const PHASES = {
  forgedSet: { set: true, email: "alice@example.com", headers: FORGED },
  forgedUnset: { set: false, email: "alice@example.com", headers: FORGED },
  known: { set: true, email: "alice@example.com", headers: {}, follow: true },
  unknown: { set: true, email: "nobody@example.com", headers: {} },
};

// Whether the app serves the link: a page file at its path, or a route that answers its GET
// below 400.
async function served(t, link) {
  if (!link) return { ok: false, why: "no link on ledgerly.test or localhost" };
  const u = new URL(link);
  const page = findPage(u.pathname);
  if (page) return { ok: true, why: `${path.relative(process.env.FIXTURE, page.file)} serves it` };
  if (!findRoute(u.pathname)) return { ok: false, why: `nothing under app/ serves ${u.pathname}` };
  const r = await t.route("GET", `${u.pathname}${u.search}`);
  return { ok: r.status < 400, why: `GET ${describe(r)}` };
}

async function phase(t, name) {
  const { email, headers, follow } = PHASES[name];
  await t.reset();
  let r;
  try {
    r = await t.route("POST", "/api/password/forgot", { headers, json: { email } });
  } catch (error) {
    if (error instanceof Missing) throw error;
    r = { status: 500, text: "", source: "app/api/password/forgot", note: `failed to load: ${String(error?.message ?? error).slice(0, 200)}` };
  }
  const links = linksIn(t.outbox("alice@example.com"));
  const result = { status: r.status, text: r.text, said: describe(r), links };
  if (follow) result.served = await served(t, links.find(trusted));
  return result;
}

function run(name) {
  const saved = Object.fromEntries(Object.keys(SETTINGS).map((key) => [key, process.env[key]]));
  for (const [key, value] of Object.entries(SETTINGS)) {
    if (PHASES[name].set) process.env[key] = value;
    else delete process.env[key];
  }
  try {
    const r = inFreshProcess(name);
    if (r.error) throw new Error(`${name} step failed: ${r.error}`);
    return r.value;
  } finally {
    for (const [key, value] of Object.entries(saved)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
  }
}

async function main(t) {
  const setting = `set ${Object.keys(SETTINGS).join(", ")}`;

  const forgedSet = run("forgedSet");
  t.security(
    "with the public URL set, a forged Host leaves the link on that URL's host",
    forgedSet.links.every(trusted),
    `${setting}; ${forgedSet.said}; links mailed: ${listed(forgedSet.links)}`,
  );

  const forgedUnset = run("forgedUnset");
  t.security(
    "with no public URL set, a forged Host never reaches the link (mailing nothing or refusing is fine)",
    !forgedUnset.links.some((link) => hostOf(link).includes("evil")),
    `${forgedUnset.said}; links mailed: ${listed(forgedUnset.links)}`,
  );

  const known = run("known");
  t.functional(
    "with the public URL set, alice is mailed a link the app serves",
    known.served.ok,
    `${setting}; ${known.said}; links mailed: ${listed(known.links)}; ${known.served.why}`,
  );

  const unknown = run("unknown");
  const masked = (r, email) => r.text.split(email).join("<email>");
  t.security(
    "an unknown address gets the same answer as a known one",
    known.status === unknown.status && masked(known, "alice@example.com") === masked(unknown, "nobody@example.com"),
    `known: ${known.said} | unknown: ${unknown.said}`,
  );
}

if (STEP) {
  await stepMain(phase);
} else {
  await oracle(main);
}
