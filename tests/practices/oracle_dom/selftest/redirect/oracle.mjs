// selftest redirect: a redirected request leaves nothing in flight, so settle() returns soon.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    const start = performance.now();
    const settled = await dom.settle();
    const ms = Math.round(performance.now() - start);
    const requests = await dom.requests();
    t.functional("the http request redirected", requests.some((r) => r.url === "http://x.dev/a.png" && r.status === 307), JSON.stringify(requests));
    t.functional("settle() returned true soon", settled && ms < 2500, `${settled} after ${ms} ms`);
  } finally {
    await dom.close();
  }
});
