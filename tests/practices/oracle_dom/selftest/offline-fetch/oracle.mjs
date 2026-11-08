// selftest offline-fetch: a request the page makes shows in requests(), failed, as nothing is
// reachable; the checks' details carry what Chrome said, for the test to read.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.settle();
    const hit = (await dom.requests()).find((r) => r.url === "https://example.com/x");
    t.functional("the fetch shows in requests()", hit, JSON.stringify(await dom.requests()));
    t.functional("it failed", hit?.failed === true, JSON.stringify(hit));
    t.functional("no response came back", hit && hit.status === null, JSON.stringify(hit));
    t.functional("the page saw the failure", (await dom.text("#state")) === "offline", await dom.text("#state"));
    t.functional("fetches() logged the call", (await dom.fetches()).some((f) => f.url === "https://example.com/x" && !f.stubbed), JSON.stringify(await dom.fetches()));
  } finally {
    await dom.close();
  }
});
