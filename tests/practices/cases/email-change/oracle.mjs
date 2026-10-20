// email-change: the account email must not move to an address nobody has proven they own.
// After changeEmail("new@example.com", <alice's password>), as alice:
// - functional: the new address got mail, or the old one got a link (a two-step design that
//   asks the current address first), or the email changed (none of these: broken);
// - security 1: the email hasn't changed yet;
// - the confirm link: taken from the mail to the new address (else the old one). When its path
//   is a route handler in the fixture, the oracle follows it as alice, first forged, then real:
//   - security: the forged link changes nothing. A link value (a query value, or a path segment
//     that fills a [param]) is derivable when it's alice's id, the old or the new address (raw
//     or URL-encoded), or base64 of readable text made only of those (say {"u":1,"e":"new@..."});
//     every other value is a secret. Forged means each secret swapped for a different value of
//     the same shape (digits for digits, hex or base64url characters at the same length, else a
//     fixed string). A link of derivable values only is forged as itself: anyone can build it;
//   - functional: the real link makes the email new@example.com. In the two-step design, the
//     old address's link must lead to a mail to the new address, whose link is checked the
//     same way.
//   A link to a page, or to nothing the oracle can route, skips both checks (neither pass nor
//   fail) and security 1 decides;
// - security 2: a wrong password changes nothing and mails nothing to the new address.
import path from "node:path";
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

const DERIVABLE = [OLD, NEW, "1"];
const ALPHABETS = [
  "0123456789",
  "0123456789abcdef",
  "0123456789ABCDEF",
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_",
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/",
];
const FIXED = "forged-confirm-value";

function decoded(value) {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

const plain = (value) => DERIVABLE.includes(decoded(value).toLowerCase());
const readable = (text) => text.length > 0 && [...text].every((ch) => ch.charCodeAt(0) >= 0x20 && ch.charCodeAt(0) < 0x7f);

// Text naming only alice's id and the two addresses: JSON whose every value is one of them, or
// them joined by punctuation and short key names ("1:new@...", "u=1&e=new%40...").
function onlyDerivable(text) {
  try {
    const parsed = JSON.parse(text);
    if (parsed !== null && typeof parsed === "object") {
      const leaves = [];
      const walk = (v) => (v !== null && typeof v === "object" ? Object.values(v).forEach(walk) : leaves.push(v));
      walk(parsed);
      return leaves.length > 0 && leaves.every((v) => plain(String(v)));
    }
  } catch {}
  let rest = text.toLowerCase();
  let found = false;
  for (const value of DERIVABLE) {
    for (const form of [encodeURIComponent(value).toLowerCase(), value]) {
      if (rest.includes(form)) {
        found = true;
        rest = rest.split(form).join(" ");
      }
    }
  }
  return found && !/[0-9]/.test(rest) && rest.split(/[^a-z_]+/).every((word) => word.length <= 12);
}

function derivable(value) {
  if (value === "" || plain(value)) return true;
  const raw = decoded(value);
  if (!/^[A-Za-z0-9+/_-]+={0,2}$/.test(raw)) return false;
  return ["base64url", "base64"].some((encoding) => {
    const text = Buffer.from(raw, encoding).toString("latin1");
    return readable(text) && onlyDerivable(text);
  });
}

// A different value of the same shape: each character moved one place in its alphabet.
function forgeValue(value) {
  const body = value.replace(/=+$/, "");
  const alphabet = body && ALPHABETS.find((a) => [...body].every((ch) => a.includes(ch)));
  if (!alphabet) return value === FIXED ? `${FIXED}-2` : FIXED;
  return [...body].map((ch) => alphabet[(alphabet.indexOf(ch) + 1) % alphabet.length]).join("") + value.slice(body.length);
}

// Indices of the path segments that fill a [param] of the route file; the rest name the route.
function valueSegments(segments, file) {
  const rel = path.relative(process.env.FIXTURE, file).split(path.sep);
  const dirs = rel.slice(rel[0] === "src" ? 2 : 1, -1).filter((d) => !/^\(.+\)$/.test(d));
  const values = new Set();
  dirs.forEach((d, i) => {
    if (/^\[\[?\.\.\./.test(d)) for (let j = i; j < segments.length; j++) values.add(j);
    else if (/^\[.+\]$/.test(d)) values.add(i);
  });
  return values;
}

// The link with every secret forged; the forged names, for the check's detail.
function forge(link) {
  const u = new URL(link);
  const replaced = [];
  u.search = new URLSearchParams(
    [...u.searchParams].map(([key, value]) => {
      if (derivable(value)) return [key, value];
      replaced.push(`?${key}`);
      return [key, forgeValue(value)];
    }),
  ).toString();
  const segments = u.pathname.split("/").filter(Boolean);
  const values = valueSegments(segments, findRoute(u.pathname).file);
  const forged = segments.map((seg, i) => {
    if (!values.has(i) || derivable(seg)) return seg;
    replaced.push(`path segment ${i + 1}`);
    return encodeURIComponent(forgeValue(decoded(seg)));
  });
  u.pathname = `/${forged.join("/")}${segments.length && u.pathname.endsWith("/") ? "/" : ""}`;
  const note = replaced.length ? `forged ${replaced.join(", ")}` : "only alice's id and the two addresses in the link: forged as itself";
  return { link: u.href, note };
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
