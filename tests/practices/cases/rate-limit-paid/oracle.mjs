// rate-limit-paid (SEC-07): a paid upstream call behind auth needs a per-account throttle.
// The abuse is one account scripting the endpoint, so the 100 rapid requests from alice each
// carry a different X-Forwarded-For and a different message: a limiter keyed only on a
// client-controlled header, or on the message, never trips and scores fail. (100, not the
// spec's 50, so a 60/min limit isn't failed.) A request counts as refused on a 429, or on any
// 4xx that never reached the provider (the provider call counter didn't move).
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
    if (r.status === 429 || (r.status >= 400 && r.status < 500 && providerCalls() === before)) refused += 1;
  }
  t.security(
    "100 rapid requests from one account hit a limit",
    refused > 0,
    `statuses ${JSON.stringify(statuses)}, provider calls ${providerCalls()}`,
  );
});
