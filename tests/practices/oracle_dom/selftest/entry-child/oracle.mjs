// selftest entry-child: an entry that isn't a page or layout starts in the client graph.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/Counter.tsx" });
  if (!dom) return;
  try {
    t.functional("the child renders", (await dom.text("#n")) === "7", await dom.text("#n"));
  } finally {
    await dom.close();
  }
});
