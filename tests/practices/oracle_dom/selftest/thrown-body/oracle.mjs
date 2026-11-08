// selftest thrown-body: an oracle body that throws without closing its session still leaves no
// Chrome behind (oracle() exits, and openDom's exit hook kills the child). A click on a missing
// selector is Missing, not a crash.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  t.functional("the page renders its text", (await dom.text("#hello")) === "hello", await dom.text("#hello"));
  t.functional("a selector that matches nothing reads null", (await dom.text("#nothing")) === null && !(await dom.exists("#nothing")));
  await dom.click("#nothing");
});
