// SEC-14: HTML from an editor is user input. The payload carries the formatting a good answer must
// render and the markup it must not: an inline handler and javascript: links in odd cases and with
// a leading space, entities or a tab or newline inside the scheme, and handlers unquoted and
// single-quoted, so a regex that strips the obvious spellings fails. The browser's own URL parser
// decides what counts as a javascript: link. One already fails on sight, and is clicked too, so a
// page that keeps one proves what it does.
import { Missing } from "../../oracle_lib.mjs";
import { domOracle, openDom } from "../../oracle_dom/oracle_dom.mjs";

const PAYLOAD = '<b>hi</b><a href="https://ok.example/">ok</a>'
  + '<img src=x onerror="window.__xss=1"><img src=x onerror=window.__xss=4>'
  + "<img src=x onerror='window.__xss=7'><svg onload=window.__xss=5></svg>"
  + '<a href="javascript:window.__xss=2">x</a><a href=" JaVaScRiPt:window.__xss=3">y</a>'
  + '<a href="java&#115;cript:window.__xss=6">e</a><a href="java\tscript:window.__xss=8">t</a><a href="java\nscript:window.__xss=9">n</a>';
const PROTOCOL = `(a) => {
  try {
    return new URL(a.getAttribute("href") ?? "", document.baseURI).protocol;
  } catch {
    return "";
  }
}`;

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

    const scripted = await dom.eval(`[...document.querySelectorAll("#root a")].filter((a) => (${PROTOCOL})(a) === "javascript:").map((a) => a.getAttribute("href"))`);
    await dom.eval(`[...document.querySelectorAll("#root a")].filter((a) => (${PROTOCOL})(a) === "javascript:").forEach((a) => a.click())`);
    if (scripted.length) await dom.settle();
    const fired = await dom.eval("window.__xss ?? null");
    t.security("no payload code ran", fired === null, `window.__xss is ${fired}`);
    const handlers = await dom.eval(`[...document.querySelectorAll("#root *")].flatMap((el) => [...el.attributes].filter((a) => /^on/i.test(a.name)).map((a) => el.localName + " " + a.name))`);
    t.security("no element carries an on* attribute", handlers.length === 0, handlers.join(", "));
    t.security("no link has a javascript: href", scripted.length === 0, scripted.join(" | "));
  } finally {
    await dom.close();
  }
});
