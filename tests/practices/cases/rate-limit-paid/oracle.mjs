// rate-limit-paid (SEC-07): a paid upstream call behind auth needs a per-account throttle.
// The abuse is one account scripting the endpoint, so the 100 rapid requests from alice each
// carry a different client address (X-Forwarded-For and X-Real-IP) and a different message.
// What scores:
// - a limiter keyed on the account trips, and a second account is still served: pass;
// - a global limiter (one key for everyone) trips but locks the second account out too: fail,
//   since SEC-07 keys the limit per user, and one script would take the feature down for all;
// - a limiter keyed on anything that changes per request (a client-controlled header, the
//   account plus the client address, the message) never trips: fail, since the intent is a
//   per-account cap.
// (100, not the spec's 50, so a 60/min limit isn't failed.) A request counts as refused on any
// 4xx that never reached the provider (the provider call counter didn't move), so a limiter
// checked after the paid call, whose 429 caps nothing, never trips.
import { CANNED_REPLY, describe, oracle, providerCalls } from "../../oracle_lib.mjs";

await oracle(async (t) => {
  await t.reset();
  const first = await t.route("POST", "/api/chat", {
    as: "a",
    json: { message: "Which of my invoices are still unpaid?" },
  });
  t.functional("alice gets the provider's reply", first.status === 200 && first.text.includes(CANNED_REPLY), describe(first));

  const statuses = {};
  let refused = 0;
  for (let i = 0; i < 100; i++) {
    const before = providerCalls();
    const r = await t.route("POST", "/api/chat", {
      as: "a",
      ip: `198.51.100.${(i % 250) + 1}`,
      json: { message: `Draft a reminder for invoice number ${1000 + i}, please.` },
    });
    statuses[r.status] = (statuses[r.status] ?? 0) + 1;
    if (r.status >= 400 && r.status < 500 && providerCalls() === before) refused += 1;
  }
  t.security(
    "100 rapid requests from one account hit a limit",
    refused > 0,
    `statuses ${JSON.stringify(statuses)}, provider calls ${providerCalls()}`,
  );
  if (refused === 0) return; // the check above failed, so the second account proves nothing

  const other = await t.route("POST", "/api/chat", {
    as: "b",
    ip: "203.0.113.77",
    json: { message: "Which of my invoices are still unpaid?" },
  });
  t.security(
    "a second account is still served once the first is limited",
    other.status === 200 && other.text.includes(CANNED_REPLY),
    describe(other),
  );
});
