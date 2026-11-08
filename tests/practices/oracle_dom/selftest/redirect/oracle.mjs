// selftest redirect: a request to an HSTS-preloaded host ends, so settle() returns soon.
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
    // Under the Fetch-domain pause every request is answered before Chrome could redirect it.
    t.functional("the request ended", requests.some((r) => r.url.endsWith("x.dev/a.png") && (r.status === 307 || r.failed)), JSON.stringify(requests));
    t.functional("settle() returned true soon", settled && ms < 2500, `${settled} after ${ms} ms`);
  } finally {
    await dom.close();
  }
});
