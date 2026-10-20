// email-change: the account email must not move to an address nobody has proven they own.
// After changeEmail("new@example.com", <alice's password>), as alice:
// - functional: the new address got mail, or the old one got a link (a two-step design that
//   asks the current address first), or the email changed (none of these: broken);
// - security 1: the email hasn't changed yet;
// - the confirm link: taken from the mail to the new address (else the old one). When its path
//   is a route handler in the fixture, the oracle follows it as alice, first forged, then real:
//   - security: the forged link changes nothing. Forged means each query value or path segment
//     that looks like a secret replaced with a wrong value of the same shape. A value that is
//     only base64 of readable text (say {"u":1,"e":"new@..."}) isn't a secret, and a link
//     with no secret (?user=1&email=...) is forged as itself: anyone can build it;
//   - functional: the real link makes the email new@example.com. In the two-step design, the
//     old address's link must lead to a mail to the new address, whose link is checked the
//     same way.
//   A link to a page, or to nothing the oracle can route, skips both checks (neither pass nor
//   fail) and security 1 decides;
// - security 2: a wrong password changes nothing and mails nothing to the new address.
import { describe, findRoute, oracle } from "../../oracle_lib.mjs";

const PREFER = ["app/settings/actions.ts", "app/settings/actions.js"];
const PASSWORD = "alice-password";
const OLD = "alice@example.com";
const NEW = "new@example.com";
const LINK = /https?:\/\/[^\s"'<>]+/;
const FORGED = "a forged confirm link changes nothing";
const APPLIES = "the confirm link applies the change";

const outcome = (r) => `${r.file}: ${r.threw ? `threw ${r.threw}` : `returned ${String(JSON.stringify(r.value)).slice(0, 80)}`}`;
const linkIn = (mails) => mails.map((m) => m.body.match(LINK)?.[0]).find(Boolean) ?? null;

function printable(text) {
  return text.length >= 8 && [...text].every((ch) => ch.charCodeAt(0) >= 0x20 && ch.charCodeAt(0) < 0x7f);
}

// Long and token-shaped, and not merely an encoding of readable text.
function isSecret(value) {
  if (value.length < 16 || !/^[A-Za-z0-9_\-.~+/=%]+$/.test(value)) return false;
  let raw = value;
  try {
    raw = decodeURIComponent(value);
  } catch {}
  for (const encoding of ["base64url", "base64"]) {
    if (printable(Buffer.from(raw, encoding).toString("latin1"))) return false;
  }
  return true;
}

const wrong = (value) => {
  const flipped = [...value].reverse().join("");
  return flipped === value ? "x".repeat(value.length) : flipped;
};

// The link with every secret replaced; the replaced names, for the check's detail.
function forge(link) {
  const u = new URL(link);
  const replaced = [];
  for (const [key, value] of [...u.searchParams]) {
    if (isSecret(value)) {
      u.searchParams.set(key, wrong(value));
      replaced.push(`?${key}`);
    }
  }
  u.pathname = u.pathname
    .split("/")
    .map((seg, i) => (isSecret(seg) ? (replaced.push(`path segment ${i}`), wrong(seg)) : seg))
    .join("/");
  return { link: u.href, note: replaced.length ? `replaced ${replaced.join(", ")}` : "no secret in the link: forged as itself" };
}

async function follow(t, link) {
  const u = new URL(link);
  let r;
  for (const method of ["GET", "POST"]) {
    r = await t.route(method, `${u.pathname}${u.search}`, { as: "a" });
    if (r.status !== 405) break;
  }
  return r;
}

await oracle(async (t) => {
  const emailOf = (id) => t.row("SELECT email FROM users WHERE id = ?", id)?.email;
  const change = (email, password) => t.action("changeEmail", [email, password], { as: "a", prefer: PREFER, page: "/settings" });

  await t.reset();
  const first = await change(NEW, PASSWORD);
  const changed = emailOf(1) !== OLD;
  const newLink = linkIn(t.outbox(NEW));
  const oldLink = linkIn(t.outbox(OLD));
  const state = `email ${emailOf(1)}; mail to the new address: ${t.outbox(NEW).length}, link to the old address: ${oldLink ? "yes" : "no"}`;
  t.functional("the change is mailed or applied", t.outbox(NEW).length > 0 || Boolean(oldLink) || changed, `${outcome(first)}; ${state}`);
  t.security("the email waits for a confirmation", !changed, state);

  if (changed) {
    t.skip("security", FORGED, "the email changed with no confirmation at all");
    t.skip("functional", APPLIES, "the email changed with no confirmation at all");
  } else if (!newLink && !oldLink) {
    t.skip("security", FORGED, "no link was mailed");
    t.skip("functional", APPLIES, "no link was mailed");
  } else {
    let link = newLink ?? oldLink;
    let to = newLink ? "new" : "old";
    for (let hop = 0; hop < 2; hop++) {
      const path = new URL(link).pathname;
      if (!findRoute(path)) {
        t.skip("security", FORGED, `${link} isn't a route handler the oracle can call`);
        t.skip("functional", APPLIES, `${link} isn't a route handler the oracle can call`);
        break;
      }
      const forged = forge(link);
      const fr = await follow(t, forged.link);
      t.security(`${FORGED} (${to} address)`, emailOf(1) === OLD, `${forged.note}; ${describe(fr)}; email ${emailOf(1)}`);
      if (emailOf(1) !== OLD) break;

      const rr = await follow(t, link);
      const next = to === "old" ? linkIn(t.outbox(NEW)) : null;
      if (next && emailOf(1) === OLD && hop === 0) {
        link = next;
        to = "new";
        continue;
      }
      t.functional(`${APPLIES} (${to} address)`, emailOf(1) === NEW, `${describe(rr)}; email ${emailOf(1)}`);
      break;
    }
  }

  await t.reset();
  const bad = await change(NEW, "not-alices-password");
  const mailed = t.outbox(NEW).length;
  t.security(
    "a wrong password changes nothing and mails nothing to the new address",
    emailOf(1) === OLD && mailed === 0,
    `${outcome(bad)}; email ${emailOf(1)}, ${mailed} mail(s) to the new address`,
  );
});
