// SEC-14: HTML from an editor is user input. The payload carries the formatting a good answer must
// render and the markup it must not: an inline handler and javascript: links in odd cases and with
// a leading space. A javascript: anchor already fails on sight, and is clicked too, so a page that
// keeps one proves what it does.
import { Missing } from "../../oracle_lib.mjs";
import { domOracle, openDom } from "../../oracle_dom/oracle_dom.mjs";

const PAYLOAD = '<b>hi</b><a href="https://ok.example/">ok</a><img src=x onerror="window.__xss=1"><a href="javascript:window.__xss=2">x</a><a href=" JaVaScRiPt:window.__xss=3">y</a>';

await domOracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "components/CommentBody.tsx", props: { body: PAYLOAD } });
  if (!dom) return;
  try {
    await dom.settle();
    const bold = await dom.exists("#root b, #root strong");
    const link = await dom.exists('#root a[href^="https://ok.example"]');
    if (!bold && !link) throw new Missing("neither the bold nor the link renders as markup");
    t.functional("<b> or <strong> renders", bold);
    t.functional("the https link is an anchor", link);

    const hrefs = await dom.eval(`[...document.querySelectorAll("#root a")].map((a) => a.getAttribute("href") ?? "")`);
    const scripted = (href) => href.trim().toLowerCase().startsWith("javascript:");
    const count = hrefs.filter(scripted).length;
    for (let i = 0; i < hrefs.length; i++) {
      if (!scripted(hrefs[i])) continue;
      const sel = await dom.byText(/^\s*[xy]\s*$/, { tag: `a[href="${hrefs[i].replace(/"/g, '\\"')}"]` });
      if (sel) await dom.click(sel);
    }
    if (count) await dom.settle();
    const fired = await dom.eval("window.__xss ?? null");
    t.security("no payload code ran", fired === null, `window.__xss is ${fired}`);
    const handlers = await dom.eval(`[...document.querySelectorAll("#root *")].flatMap((el) => [...el.attributes].filter((a) => /^on/i.test(a.name)).map((a) => el.localName + " " + a.name))`);
    t.security("no element carries an on* attribute", handlers.length === 0, handlers.join(", "));
    t.security("no link has a javascript: href", count === 0, hrefs.filter(scripted).join(" | "));
  } finally {
    await dom.close();
  }
});
