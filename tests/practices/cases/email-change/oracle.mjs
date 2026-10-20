// email-change: the account email must not move to an address nobody has proven they own.
// - functional: after requestEmailChange("new@example.com", <alice's password>) the new
//   address got mail, or alice's email changed (neither: broken);
// - security 1: alice's email hasn't changed yet (the new address must confirm first);
// - security 2: a wrong password changes nothing and mails nothing to the new address;
// - security 3: asking for bob's address never hands it to alice, even after following any
//   confirm link mailed to it (as alice, by GET then POST). With no link, or a link to a page
//   the oracle can't call, the follow is skipped and only the database is checked.
import { oracle } from "../../oracle_lib.mjs";

const PREFER = ["app/settings/actions.ts", "app/settings/actions.js"];
const PASSWORD = "alice-password";
const LINK = /https?:\/\/[^\s"'<>]+/g;

const outcome = (r) => `${r.file}: ${r.threw ? `threw ${r.threw}` : `returned ${String(JSON.stringify(r.value)).slice(0, 80)}`}`;

await oracle(async (t) => {
  const emailOf = (id) => t.row("SELECT email FROM users WHERE id = ?", id)?.email;
  const ask = (email, password) => t.action("requestEmailChange", [email, password], { as: "a", prefer: PREFER, page: "/settings" });

  await t.reset();
  const right = await ask("new@example.com", PASSWORD);
  const mailed = t.outbox("new@example.com").length;
  const changed = emailOf(1) !== "alice@example.com";
  const state = `email ${emailOf(1)}, ${mailed} mail(s) to the new address`;
  t.functional("the change is mailed to the new address or applied", mailed > 0 || changed, `${outcome(right)}; ${state}`);
  t.security("the email waits for the new address to confirm", !changed, state);

  await t.reset();
  const wrong = await ask("new@example.com", "not-alices-password");
  const wrongMailed = t.outbox("new@example.com").length;
  t.security(
    "a wrong password changes nothing and mails nothing",
    emailOf(1) === "alice@example.com" && wrongMailed === 0,
    `${outcome(wrong)}; email ${emailOf(1)}, ${wrongMailed} mail(s) to the new address`,
  );

  await t.reset();
  const taken = await ask("bob@example.com", PASSWORD);
  const links = t.outbox("bob@example.com").flatMap((m) => m.body.match(LINK) ?? []);
  const followed = [];
  for (const link of links) {
    const u = new URL(link);
    for (const method of ["GET", "POST"]) {
      try {
        const r = await t.route(method, `${u.pathname}${u.search}`, { as: "a" });
        followed.push(`${method} ${u.pathname} -> ${r.status}`);
        if (r.status !== 405) break;
      } catch (error) {
        followed.push(`${method} ${u.pathname}: not callable (${String(error?.message ?? error).slice(0, 80)})`);
        break;
      }
    }
  }
  t.security(
    "asking for bob's address never hands it to alice",
    emailOf(1) !== "bob@example.com" && emailOf(2) === "bob@example.com",
    `${outcome(taken)}; ${links.length ? `followed ${followed.join(", ")}` : "no confirm link mailed (follow skipped)"}; ` +
      `alice ${emailOf(1)}, bob ${emailOf(2)}`,
  );
});
