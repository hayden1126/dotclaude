// selftest abort-storm: requests the page aborts aren't tampering and don't hold settle(), and a
// path with a bad percent-escape neither flags nor stalls.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    const start = performance.now();
    const settled = await dom.settle();
    const ms = Math.round(performance.now() - start);
    t.functional("settle() returned true under the cap", settled && ms < 4000, `${settled} after ${ms} ms`);
    t.functional("the odd path failed as offline", (await dom.text("#odd")) === "failed", await dom.text("#odd"));
  } finally {
    await dom.close();
  }
});
