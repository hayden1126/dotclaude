// selftest css-edges: the CSS inliner skips a commented-out @import, and leaves out (with a
// note, unread) an @import of a path outside the project, whether ../ past its root or absolute.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    t.functional("the sheet applies", (await dom.style("#edge", "width")) === "17px", await dom.style("#edge", "width"));
    const css = await dom.eval("[...document.querySelectorAll('style')].map((s) => s.textContent).join('\\n')");
    t.functional("an import outside the project is left out with a note", (css.match(/left out/g) ?? []).length === 2, css.slice(0, 600));
  } finally {
    await dom.close();
  }
});
