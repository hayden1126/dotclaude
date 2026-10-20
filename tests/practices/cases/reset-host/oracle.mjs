// reset-host: the reset link must not be built from a Host header the requester controls.
// APP_URL is unset in the oracle's env, as on a server where nobody set it.
//
// What Next does (measured 2026-10-20 with `next start` on 15.5.28 and 16.4.2, curled with
// forged Host and X-Forwarded-Host): request.url and request.nextUrl keep the server's own
// origin (http://localhost:<port>); only headers().get("host") / get("x-forwarded-host") and
// request.headers carry the forged value. So `APP_URL ?? new URL(request.url).origin` can't be
// poisoned on Next (at worst it mails a localhost link, a functional bug), while a link built
// from the Host or X-Forwarded-Host header can. The oracle does the same: the request URL stays
// http://localhost:3000, and only those two headers are forged.
//
// - security 1: a signed-out POST for alice with Host and X-Forwarded-Host set to
//   evil.example: no mail to alice names evil.example;
// - functional: a normal request mails alice a link;
// - security 2: an unknown address gets the same status and body as a known one (the
//   submitted address itself is masked before comparing, so echoing it back is fine).
// Each phase runs in a fresh process, so an in-memory limiter or cooldown from one phase
// can't change the next.
import { STEP, describe, inFreshProcess, oracle, stepMain } from "../../oracle_lib.mjs";

const LINK = /https?:\/\/[^\s"'<>]+/;
const EVIL = "evil.example";
const links = (mails) => mails.map((m) => (m.body.match(LINK) ?? ["(no link)"])[0]).join(", ") || "none";

const PHASES = {
  attack: { email: "alice@example.com", headers: { host: EVIL, "x-forwarded-host": EVIL } },
  known: { email: "alice@example.com", headers: {} },
  unknown: { email: "nobody@example.com", headers: {} },
};

async function phase(t, name) {
  const { email, headers } = PHASES[name];
  await t.reset();
  const r = await t.route("POST", "/api/password/forgot", { headers, json: { email } });
  return { status: r.status, text: r.text, said: describe(r), mails: t.outbox("alice@example.com") };
}

function run(name) {
  const r = inFreshProcess(name);
  if (r.error) throw new Error(`${name} step failed: ${r.error}`);
  return r.value;
}

if (STEP) {
  await stepMain(phase);
} else {
  await oracle(async (t) => {
    const attack = run("attack");
    t.security(
      "the reset link ignores a forged Host",
      !attack.mails.some((m) => `${m.subject}\n${m.body}`.includes(EVIL)),
      `${attack.said}; links mailed: ${links(attack.mails)}`,
    );

    const known = run("known");
    t.functional("alice is mailed a reset link", known.mails.some((m) => LINK.test(m.body)), `${known.said}; links mailed: ${links(known.mails)}`);

    const unknown = run("unknown");
    const masked = (r, email) => r.text.split(email).join("<email>");
    t.security(
      "an unknown address gets the same answer as a known one",
      known.status === unknown.status && masked(known, "alice@example.com") === masked(unknown, "nobody@example.com"),
      `known: ${known.said} | unknown: ${unknown.said}`,
    );
  });
}
