// selftest inline-script: an inline <script> in the first render executes, as a server-rendered
// page's does, once; one React adds on a later render stays inert, as in Next; a script a client
// effect inserted during the first render isn't run a second time.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.settle();
    t.functional("the first render's inline script ran once", (await dom.eval("window.ranFirst")) === 1, String(await dom.eval("window.ranFirst")));
    t.functional("an effect's script ran once", (await dom.eval("window.ranEffect")) === 1, String(await dom.eval("window.ranEffect")));
    await dom.click("button");
    await dom.settle();
    t.functional("a later render's inline script stays inert", (await dom.eval("window.ranLater ?? 0")) === 0, String(await dom.eval("window.ranLater")));
  } finally {
    await dom.close();
  }
});
