// selftest cors: a stubbed cross-origin fetch with credentials and a custom header succeeds, and
// counts once (its preflight isn't a fetch).
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx", fetchModes: [["api.example", { json: { name: "Ada" } }]] });
  if (!dom) return;
  try {
    await dom.settle();
    t.functional("the credentialed fetch gets its stub", (await dom.text("#state")) === "Ada", await dom.text("#state"));
    const fetches = await dom.fetches();
    t.functional("it counts once", fetches.length === 1 && fetches[0].method === "GET", JSON.stringify(fetches));
  } finally {
    await dom.close();
  }
});
