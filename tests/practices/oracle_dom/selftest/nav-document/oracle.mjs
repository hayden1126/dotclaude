// selftest nav-document: a followed link and a form post are recorded in navigations(), the
// current document stays, and settle() still works.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.click("#pricing");
    t.functional("settle() works after a link", await dom.settle());
    await dom.click("#post");
    t.functional("settle() works after a form post", await dom.settle());
    const navigations = await dom.navigations();
    t.functional("the link is recorded", navigations.some((n) => n.url === "/pricing" && n.method === "GET"), JSON.stringify(navigations));
    t.functional("the form post is recorded", navigations.some((n) => n.url === "/x" && n.method === "POST"), JSON.stringify(navigations));
    t.functional("the page stayed", await dom.exists("#pricing"));
  } finally {
    await dom.close();
  }
});
