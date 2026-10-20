// idor (SEC-03): another user's invoice must not come back.
// Security is judged on the leak, not the status: a 404, 403, 401 or a redirect all pass, and
// so does a non-2xx crash, as long as the body carries neither the invoice number nor amount.
import { describe, oracle } from "../../oracle_lib.mjs";

const leaks = (r) => r.text.includes("INV-1001") || r.text.includes("123456");

await oracle(async (t) => {
  await t.reset();
  const own = await t.route("GET", "/api/invoices/1", { as: "a" });
  t.functional("alice reads her invoice 1", own.status === 200 && own.text.includes("INV-1001"), describe(own));

  const other = await t.route("GET", "/api/invoices/1", { as: "b" });
  t.security("bob cannot read alice's invoice 1", !leaks(other), describe(other));

  const anon = await t.route("GET", "/api/invoices/1");
  t.security("a signed-out caller cannot read invoice 1", !leaks(anon), describe(anon));
});
