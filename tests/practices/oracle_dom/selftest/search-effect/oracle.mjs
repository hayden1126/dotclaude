// selftest search-effect: an effect keyed on useSearchParams() fetches exactly once.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx", search: "q=shoes", fetchModes: [["api.example", { json: [] }]] });
  if (!dom) return;
  try {
    await dom.settle({ ms: 2000 });
    const fetches = await dom.fetches();
    t.functional("the effect fetched exactly once", fetches.length === 1, `${fetches.length} fetches`);
  } finally {
    await dom.close();
  }
});
