// selftest page-props: an entry gets params and searchParams as Promises, as Next 15 passes them.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  for (const [entry, sel, want] of [["app/dom/client/page.tsx", "#slug", "abc"], ["app/dom/server/page.tsx", "#q", "hi|a,b"]]) {
    const dom = await openDom(t, import.meta.url, { entry, params: { slug: "abc" }, search: "q=hi&tag=a&tag=b" });
    if (!dom) return;
    try {
      await dom.settle();
      t.functional(`${entry} reads its page props`, (await dom.text(sel)) === want, await dom.html());
    } finally {
      await dom.close();
    }
  }
});
