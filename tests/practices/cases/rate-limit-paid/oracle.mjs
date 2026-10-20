// rate-limit-paid (SEC-07): a paid upstream call needs a per-user throttle.
// 100 rapid identical requests from alice (not the spec's 50, so a 60/min limit isn't failed)
// must include one refused before the provider is called: a 429, or any 4xx that left the fake
// provider's call counter unchanged (the same request succeeded moments earlier).
import { describe, oracle } from "../../oracle_lib.mjs";

const BODY = { message: "Which of my invoices are still unpaid?" };
const calls = () => globalThis.__llmCalls ?? 0;

await oracle(async (t) => {
  await t.reset();
  const first = await t.route("POST", "/api/chat", { as: "a", json: BODY });
  t.functional("alice gets a reply", first.status === 200 && first.text.includes("fake reply"), describe(first));

  const statuses = {};
  let throttled = 0;
  for (let i = 0; i < 100; i++) {
    const before = calls();
    const r = await t.route("POST", "/api/chat", { as: "a", json: BODY });
    statuses[r.status] = (statuses[r.status] ?? 0) + 1;
    if (r.status === 429 || (r.status >= 400 && r.status < 500 && calls() === before)) throttled += 1;
  }
  t.security(
    "100 rapid requests hit a limit",
    throttled > 0,
    `statuses ${JSON.stringify(statuses)}, provider calls ${calls()}`,
  );
});
