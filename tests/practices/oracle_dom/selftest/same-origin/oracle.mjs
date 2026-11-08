// selftest same-origin: a relative fetch goes through the rules and the logs like any other: a
// stub by its path, a failure when nothing matches, both in fetches(). A blob: image renders.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx", fetchModes: [[/^\/api\/save$/, { json: { ok: true } }]] });
  if (!dom) return;
  try {
    await dom.settle();
    t.functional("a relative fetch gets its stub", (await dom.text("#saved")) === "true", await dom.text("#saved"));
    t.functional("an unmatched relative fetch fails", (await dom.text("#missing")) === "failed", await dom.text("#missing"));
    const fetches = await dom.fetches();
    t.functional("fetches() has the stubbed one", fetches.some((f) => f.url === "/api/save" && f.method === "POST" && f.stubbed), JSON.stringify(fetches));
    t.functional("fetches() has the unmatched one", fetches.some((f) => f.url === "/api/none" && !f.stubbed), JSON.stringify(fetches));
    const requests = await dom.requests();
    t.functional("requests() has the failed one", requests.some((r) => r.url === "/api/none" && r.failed), JSON.stringify(requests));
    const width = await dom.eval("document.querySelector('#preview')?.naturalWidth ?? null");
    t.functional("a blob: image renders", width === 3, String(width));
  } finally {
    await dom.close();
  }
});
