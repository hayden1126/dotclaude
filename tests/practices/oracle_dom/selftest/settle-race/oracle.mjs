// selftest settle-race: settle() returns only once a stubbed fetch's result has committed, on a
// page with no loading UI, 100 times in a row.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx", delayMs: 0, fetchModes: [["api.example", { json: 1 }]] });
  if (!dom) return;
  try {
    const misses = [];
    for (let i = 1; i <= 100; i++) {
      await dom.click("button");
      await dom.settle({ quiet: 20 });
      const seen = await dom.text("#done");
      if (seen !== String(i)) misses.push(`${i}: ${seen}`);
    }
    t.functional("settle() saw every result", misses.length === 0, `${misses.length} misses: ${misses.slice(0, 5).join(", ")}`);
  } finally {
    await dom.close();
  }
});
