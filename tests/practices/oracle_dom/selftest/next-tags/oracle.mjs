// selftest next-tags: the next/* stubs keep what oracles read. next/script requests its src by
// strategy, next/image keeps width, height and loading, next/link prints its href, and
// next/font/google records the family with no request.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.settle();
    const urls = (await dom.requests()).map((r) => r.url);
    t.functional("an afterInteractive script is requested", urls.includes("https://tracker.example/t.js"), JSON.stringify(urls));
    t.functional("a lazyOnload script is requested after load", urls.includes("https://widgets.example/chat.js"), JSON.stringify(urls));
    t.functional("the script carries its strategy", (await dom.attr('script[src="https://tracker.example/t.js"]', "data-strategy")) === "afterInteractive");
    t.functional("the script keeps async", (await dom.attr('script[src="https://tracker.example/t.js"]', "async")) === "");
    const hero = 'img[alt="Hero"]';
    t.functional("the image keeps its width", (await dom.attr(hero, "width")) === "640", await dom.attr(hero, "width"));
    t.functional("the image keeps its height", (await dom.attr(hero, "height")) === "320", await dom.attr(hero, "height"));
    t.functional("an image loads lazy by default", (await dom.attr(hero, "loading")) === "lazy", await dom.attr(hero, "loading"));
    const logo = 'img[alt="Logo"]';
    t.functional("priority means eager", (await dom.attr(logo, "loading")) === "eager", await dom.attr(logo, "loading"));
    t.functional("priority means fetchpriority=high", (await dom.attr(logo, "fetchpriority")) === "high", await dom.attr(logo, "fetchpriority"));
    t.functional("the link prints its href", (await dom.attr("a", "href")) === "/pricing?plan=pro", await dom.attr("a", "href"));
    const fonts = await dom.fonts();
    t.functional("the font family is recorded", fonts.some((f) => f.family === "Inter"), JSON.stringify(fonts));
    t.functional("the font sent no request", !urls.some((u) => /fonts\.(googleapis|gstatic)/.test(u)), JSON.stringify(urls));
  } finally {
    await dom.close();
  }
});
