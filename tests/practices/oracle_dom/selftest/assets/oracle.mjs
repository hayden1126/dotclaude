// selftest assets: an image import is Next's static image ({src, width, height}, its src served
// from the scratch dir), a relative CSS @import is inlined (main.css and base.css import each
// other), and a URL @import stays as written.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.settle();
    t.functional("image imports carry their dimensions", (await dom.text("#dims")) === "3x2 5x4 8x8", await dom.text("#dims"));
    const loaded = await dom.eval("document.querySelector('#hero').complete && document.querySelector('#hero').naturalWidth");
    t.functional("an imported image's src loads", loaded === 3, `${await dom.attr("#hero", "src")}: ${loaded}`);
    t.functional("a relative @import is inlined", (await dom.style("#base", "width")) === "42px", await dom.style("#base", "width"));
    t.functional("the importing sheet still applies", (await dom.style("main", "padding-top")) === "3px", await dom.style("main", "padding-top"));
    const css = await dom.eval("[...document.querySelectorAll('style')].map((s) => s.textContent).join('\\n')");
    t.functional("a URL @import stays", css.includes('@import url("https://fonts.example/x.css")'), css.slice(0, 600));
  } finally {
    await dom.close();
  }
});
