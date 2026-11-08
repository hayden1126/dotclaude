// selftest storage: opts.storage is in place before the first render.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx", storage: { local: { consent: "granted" }, session: { draft: "hello" } } });
  if (!dom) return;
  try {
    t.functional("localStorage is set at first render", (await dom.text("#consent")) === "granted", await dom.text("#consent"));
    t.functional("sessionStorage is set at first render", (await dom.text("#draft")) === "hello", await dom.text("#draft"));
  } finally {
    await dom.close();
  }
});
