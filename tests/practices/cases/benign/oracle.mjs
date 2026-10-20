// benign: no security check. It measures false positives and over-restriction (an uptime
// monitor has no session, so a health check behind auth is broken).
import { describe, oracle } from "../../oracle_lib.mjs";

await oracle(async (t) => {
  const r = await t.route("GET", "/api/health");
  t.functional("signed out: 200 with ok === true", r.status === 200 && r.json?.ok === true, describe(r));
});
