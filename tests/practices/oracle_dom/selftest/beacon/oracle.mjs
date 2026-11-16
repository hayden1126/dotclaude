// selftest beacon: a navigator.sendBeacon request shows in requests() and doesn't stall settle().
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    const start = performance.now();
    const settled = await dom.settle();
    const ms = Math.round(performance.now() - start);
    t.functional("settle() returned true soon", settled && ms < 2500, `${settled} after ${ms} ms`);
    const requests = await dom.requests();
    t.functional("the beacon shows", requests.some((r) => r.url === "https://metrics.example/hit"), JSON.stringify(requests));
  } finally {
    await dom.close();
  }
});
