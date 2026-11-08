// selftest dynamic-unresolved: next/dynamic of a component that reaches server-only code scores
// unresolved, not broken.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.settle();
    const errors = await dom.errors();
    t.functional("nothing threw on render", errors.length === 0, errors.join("\n").slice(0, 600));
  } finally {
    await dom.close();
  }
});
