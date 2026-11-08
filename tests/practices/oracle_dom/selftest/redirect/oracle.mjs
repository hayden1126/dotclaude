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
    // Under the Fetch-domain pause the request is answered before Chrome would redirect it; a
    // redirect it does follow marks the first leg done, so either way nothing stays in flight.
    t.functional("the request ended", requests.some((r) => r.url.endsWith("x.dev/a.png") && (r.status === 307 || r.failed)), JSON.stringify(requests));
    t.functional("settle() returned true soon", settled && ms < 2500, `${settled} after ${ms} ms`);
  } finally {
    await dom.close();
  }
});
