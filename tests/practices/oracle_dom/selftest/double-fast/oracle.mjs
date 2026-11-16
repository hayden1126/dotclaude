// selftest double-fast: with a round trip shorter than the gap between two clicks, a page that
// disables its button while pending still sends one action, as the answer waits for click() to
// return. A "hang" action isn't held: it never answers, and settle() still returns.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx", delayMs: 40 });
  if (!dom) return;
  try {
    await dom.click("button[type=submit]", { count: 2 });
    await dom.settle();
    const actions = await dom.actions();
    t.security("a double click sends one action", actions.length === 1, `${actions.length} sent`);
    await dom.actionMode("subscribe", "hang");
    await dom.click("button[type=submit]");
    t.functional("settle() returns with a hanging action", await dom.settle());
    t.functional("the hanging action was sent", (await dom.actions()).length === 2, JSON.stringify(await dom.actions()));
    t.functional("the page is still pending on it", (await dom.attr("button[type=submit]", "disabled")) !== null);
  } finally {
    await dom.close();
  }
});
