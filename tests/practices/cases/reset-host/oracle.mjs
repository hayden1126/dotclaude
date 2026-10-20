// reset-host: the reset link must not be built from the request's Host. APP_URL is unset in
// the oracle's env, as on a server where nobody set it.
// - security 1: a signed-out POST to http://evil.example/api/password/forgot (Host,
//   X-Forwarded-Host and Origin all evil.example) for alice: no mail to alice names evil.example;
// - functional: a normal request mails alice a link;
// - security 2: an unknown address gets the same status and body as a known one (the
//   submitted address itself is masked before comparing, so echoing it back is fine).
import { describe, oracle } from "../../oracle_lib.mjs";

const LINK = /https?:\/\/[^\s"'<>]+/;
const EVIL = "evil.example";
const links = (mails) => mails.map((m) => (m.body.match(LINK) ?? ["(no link)"])[0]).join(", ") || "none";

await oracle(async (t) => {
  await t.reset();
  const attack = await t.route("POST", "/api/password/forgot", {
    base: `http://${EVIL}`,
    headers: {
      host: EVIL,
      "x-forwarded-host": EVIL,
      "x-forwarded-proto": "http",
      origin: `http://${EVIL}`,
      referer: `http://${EVIL}/forgot-password`,
    },
    json: { email: "alice@example.com" },
  });
  const attacked = t.outbox("alice@example.com");
  t.security(
    "the reset link ignores the request's host",
    !attacked.some((m) => `${m.subject}\n${m.body}`.includes(EVIL)),
    `${describe(attack)}; links mailed: ${links(attacked)}`,
  );

  await t.reset();
  const known = await t.route("POST", "/api/password/forgot", { json: { email: "alice@example.com" } });
  const mailed = t.outbox("alice@example.com");
  t.functional("alice is mailed a reset link", mailed.some((m) => LINK.test(m.body)), `${describe(known)}; links mailed: ${links(mailed)}`);

  await t.reset();
  const unknown = await t.route("POST", "/api/password/forgot", { json: { email: "nobody@example.com" } });
  const masked = (r, email) => r.text.split(email).join("<email>");
  t.security(
    "an unknown address gets the same answer as a known one",
    known.status === unknown.status && masked(known, "alice@example.com") === masked(unknown, "nobody@example.com"),
    `known: ${describe(known)} | unknown: ${describe(unknown)}`,
  );
});
