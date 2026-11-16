// selftest third-parties: @next/third-parties/google, once the project declares it, inserts the
// real googletagmanager script so the request shows.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.settle();
    const urls = (await dom.requests()).map((r) => r.url);
    t.functional("GoogleAnalytics loads gtag", urls.includes("https://www.googletagmanager.com/gtag/js?id=G-TEST"), urls.join(" "));
    t.functional("GoogleTagManager loads gtm", urls.includes("https://www.googletagmanager.com/gtm.js?id=GTM-TEST"), urls.join(" "));
  } finally {
    await dom.close();
  }
});
