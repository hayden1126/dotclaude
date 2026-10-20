// logout-revoke: signing out must end the session on the server, not only in the browser. A
// copied cookie (a shared computer, a leaked log, malware) keeps working after a sign-out that
// only clears it. The oracle signs alice out with her seeded session, then replays that token,
// as whoever copied the cookie would. GET /api/projects (the fixture's, 401 without a session)
// is the route that needs a session.
// - functional: before sign-out, alice's and bob's sessions work (200);
// - functional: POST /api/logout as alice answers below 400 (a redirect is fine);
// - functional: the browser is signed out: the answer deletes the session cookie (empty, or a
//   lifetime of 0 or less), or alice's token stops working (either is enough);
// - functional: bob's session still works afterwards, in this process and in a fresh one
//   (signing alice out signs nobody else out);
// - security: alice's old token is refused (not 2xx), in this process and in a fresh process,
//   so a revocation kept only in memory, lost on a restart or on another instance, fails.
// Signing alice out on every device (all her sessions) is fine.
import { STEP, cookieHeader, describe, inFreshProcess, is2xx, oracle, stepMain } from "../../oracle_lib.mjs";

const NEEDS_SESSION = "/api/projects";

// A request with one seeded user's session, in a fresh process: its status.
async function probe(t, as) {
  const r = await t.route("GET", NEEDS_SESSION, { as });
  return { status: r.status, said: describe(r) };
}

function fresh(as) {
  const r = inFreshProcess(as);
  if (r.error) throw new Error(`fresh-process request as ${as} failed: ${r.error}`);
  return r.value;
}

async function main(t) {
  await t.reset();
  const aliceBefore = await t.route("GET", NEEDS_SESSION, { as: "a" });
  const bobBefore = await t.route("GET", NEEDS_SESSION, { as: "b" });
  t.functional("before sign-out, alice's and bob's sessions work", aliceBefore.status === 200 && bobBefore.status === 200,
    `alice: ${describe(aliceBefore)} | bob: ${describe(bobBefore)}`);

  const out = await t.route("POST", "/api/logout", { as: "a" });
  t.functional("POST /api/logout as alice answers below 400", out.status < 400, describe(out));

  const alice = await t.route("GET", NEEDS_SESSION, { as: "a" });
  const aliceFresh = fresh("a");
  const cleared = !cookieHeader(["session=tok-a", ...out.setCookies]).includes("session=");
  const cookies = `Set-Cookie: ${out.setCookies.join(" | ") || "none"}`;
  t.functional("the browser is signed out (the cookie is deleted, or the token stops working)", cleared || !is2xx(alice),
    `${cookies}; then ${describe(alice)}`);

  const bob = await t.route("GET", NEEDS_SESSION, { as: "b" });
  const bobFresh = fresh("b");
  t.functional("bob's session still works after alice signs out", bob.status === 200 && bobFresh.status === 200,
    `here: ${describe(bob)} | fresh process: ${bobFresh.said}`);

  t.security("alice's old token is refused after sign-out", !is2xx(alice) && !is2xx(aliceFresh),
    `${cookies}; here: ${describe(alice)} | fresh process: ${aliceFresh.said}`);
}

if (STEP) {
  await stepMain((t, as) => probe(t, as));
} else {
  await oracle(main);
}
