// selftest memo-entry: a memo() default export renders.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    t.functional("the memo page renders its text", (await dom.text("#m")) === "memo", await dom.html());
  } finally {
    await dom.close();
  }
});
