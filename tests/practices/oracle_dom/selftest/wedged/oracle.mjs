// selftest wedged: agent code that never returns scores broken: Chrome itself still answers.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  await dom.close();
});
