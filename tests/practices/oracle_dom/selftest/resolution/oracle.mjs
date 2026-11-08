// selftest resolution: CSS, CSS modules and JSON imports, ./x.js naming x.tsx, next/dynamic and
// next/form all load and render.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.settle();
    t.functional("a CSS module's class applies", (await dom.style("#box", "width")) === "123px", await dom.style("#box", "width"));
    t.functional("a CSS module maps a class to itself", (await dom.attr("#box", "class")) === "box", await dom.attr("#box", "class"));
    t.functional("a global stylesheet applies", (await dom.style("main", "padding-top")) === "7px", await dom.style("main", "padding-top"));
    t.functional("a JSON import is its value", (await dom.text("#json")) === "from json", await dom.text("#json"));
    t.functional("./widget.js names widget.tsx", (await dom.text("#widget")) === "widget", await dom.text("#widget"));
    t.functional("next/dynamic renders its import", (await dom.text("#lazy")) === "lazy", await dom.html());
    t.functional("next/form is a plain form", (await dom.attr("form#search", "action")) === "/search", await dom.attr("form#search", "action"));
  } finally {
    await dom.close();
  }
});
