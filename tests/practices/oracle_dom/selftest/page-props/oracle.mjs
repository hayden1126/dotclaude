// selftest page-props: an entry gets params and searchParams as Next 15 passes them: Promises
// that also carry the values for a synchronous read, with keys like `constructor` as plain keys.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

const PAGES = [
  ["app/dom/client/page.tsx", "#slug", "abc", "q=hi"],
  ["app/dom/server/page.tsx", "#q", "hi|a,b", "q=hi&tag=a&tag=b"],
  ["app/dom/sync/page.tsx", "#sync", "abc", ""],
  ["app/dom/inherited/page.tsx", "#sp", '{"constructor":"1","toString":"x"}', "constructor=1&toString=x"],
];

await oracle(async (t) => {
  for (const [entry, sel, want, search] of PAGES) {
    const dom = await openDom(t, import.meta.url, { entry, params: { slug: "abc" }, search });
    if (!dom) return;
    try {
      await dom.settle();
      t.functional(`${entry} reads its page props`, (await dom.text(sel)) === want, await dom.text(sel));
    } finally {
      await dom.close();
    }
  }
});
