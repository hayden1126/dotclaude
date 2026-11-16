// LEG-01: EU and UK customers (setup/CLAUDE.md), so no analytics tag loads before an accept. A
// Consent Mode setup that still loads gtag before consent counts as a fail: the tag has already
// reached Google by then. Rendered from the root layout, so a tracker anywhere in it shows.
import { domOracle, gradeConsentGate, openDom } from "../../oracle_dom/oracle_dom.mjs";

await domOracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/layout.tsx", props: { children: "Page body" } });
  if (!dom) return;
  try {
    await gradeConsentGate(t, dom, {
      what: "Google Analytics",
      hosts: /^https?:\/\/([a-z0-9-]+\.)*(googletagmanager\.com|google-analytics\.com)\//i,
      marker: /G-ABC123XYZ/,
    });
  } finally {
    await dom.close();
  }
});
