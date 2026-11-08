// selftest builtin-polyfilled: a client component importing a builtin Next polyfills scores
// unresolved, since the oracle doesn't polyfill it.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  await dom.close();
});
