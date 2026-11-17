// selftest log-roundtrip: actions() read right after click(), with no settle, has the click's call.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx", actionModes: { subscribe: "hang" } });
  if (!dom) return;
  try {
    const misses = [];
    for (let i = 1; i <= 20; i++) {
      await dom.click("button");
      const n = (await dom.actions()).length;
      if (n !== i) misses.push(`${i}: ${n}`);
    }
    t.functional("actions() saw every click", misses.length === 0, `${misses.length} misses: ${misses.slice(0, 5).join(", ")}`);
  } finally {
    await dom.close();
  }
});
