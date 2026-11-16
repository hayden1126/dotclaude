// selftest timers: settle() doesn't see a page's timers, wait() does the waiting, and a settle or
// wait past its cap says so instead of quietly cutting it short.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

const refused = (fn) => fn().then(() => false, () => true);

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.click("button");
    await dom.settle();
    t.functional("settle() doesn't wait for a timer", (await dom.actions()).length === 0, JSON.stringify(await dom.actions()));
    await dom.wait(1500);
    t.functional("wait() does", (await dom.actions()).length === 1, JSON.stringify(await dom.actions()));
    t.functional("settle past its cap throws", await refused(() => dom.settle({ ms: 6000 })));
    t.functional("wait past its cap throws", await refused(() => dom.wait(60000)));
  } finally {
    await dom.close();
  }
});
