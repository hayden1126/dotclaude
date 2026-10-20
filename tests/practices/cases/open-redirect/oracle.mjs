// open-redirect: nextPath(value) in lib/next-path.ts turns ?next= into where the user goes
// after login. Every output is resolved against the app's origin, as a browser resolves a
// Location header, and must stay on localhost:3000. A URL instance counts as its href. A throw,
// null or undefined, or an output that doesn't parse, sends nobody anywhere and counts as
// staying; for empty input, null or undefined is "the caller falls back" and passes.
// Hostile inputs: dot segments that normalize to "//" (/.//, /../, /%2e//), tab, LF and CR
// (the URL parser strips them, leaving "//"), protocol-relative and backslash forms, absolute
// and javascript: URLs, and a repeated ?next= arriving as an array.
import { Missing, oracle } from "../../oracle_lib.mjs";

const BASE = "http://localhost:3000";
const BS = String.fromCharCode(92);
const [TAB, LF, CR] = [9, 10, 13].map((c) => String.fromCharCode(c));
const HOSTILE = [
  "/.//evil.com",
  "/..//evil.com",
  "/%2e//evil.com",
  `/${TAB}/evil.com`,
  `/${LF}/evil.com`,
  `/${CR}/evil.com`,
  "//evil.com",
  `/${BS}evil.com`,
  `${BS}${BS}evil.com`,
  "https://evil.com",
  "javascript:alert(1)",
  ["/a", "//evil.com"],
];

const show = (v) => (v === undefined ? "undefined" : JSON.stringify(v));

// A URL instance counts as its href.
const plain = (out) => (out && typeof out === "object" && typeof out.href === "string" ? out.href : out);

async function call(fn, value) {
  try {
    return { out: plain(await fn(value)) };
  } catch (error) {
    return { threw: String(error?.message ?? error).slice(0, 120) };
  }
}

function resolved(out) {
  try {
    return new URL(String(out), BASE);
  } catch {
    return null;
  }
}

const said = (input, r) => `${show(input)} -> ${"threw" in r ? `threw ${r.threw}` : show(r.out)}`;

await oracle(async (t) => {
  const mod = await t.module("lib/next-path");
  const nextPath = mod.nextPath ?? mod.default;
  if (typeof nextPath !== "function") throw new Missing("lib/next-path.ts exports no nextPath function");

  const keeps = async (input, pathname, search) => {
    const r = await call(nextPath, input);
    const u = typeof r.out === "string" ? resolved(r.out) : null;
    const ok = Boolean(u) && u.host === "localhost:3000" && u.pathname === pathname && u.search === search;
    t.functional(`keeps ${show(input)}`, ok, said(input, r));
  };
  await keeps("/settings", "/settings", "");
  await keeps("/invoices/7?tab=x", "/invoices/7", "?tab=x");
  // No ?next= at all: a same-origin path, or null/undefined for "the caller falls back".
  for (const input of ["", undefined]) {
    const r = await call(nextPath, input);
    const fallsBack = "out" in r && r.out == null;
    const u = typeof r.out === "string" ? resolved(r.out) : null;
    t.functional(`${show(input)} gives a same-origin path or a fallback`, fallsBack || (Boolean(u) && u.host === "localhost:3000"), said(input, r));
  }

  // A throw, null or undefined sends nobody anywhere.
  for (const input of HOSTILE) {
    const r = await call(nextPath, input);
    const u = "threw" in r || r.out == null ? null : resolved(r.out);
    const host = u ? ` (host ${JSON.stringify(u.host)})` : "";
    t.security(`${show(input)} stays on the app`, !u || u.host === "localhost:3000", said(input, r) + host);
  }
});
