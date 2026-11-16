// LEG-04: EU and UK customers (setup/CLAUDE.md), so session replay starts only after an accept. A
// Hotjar snippet that sets window.hj or _hjSettings counts as wired even if its script request
// doesn't show. Rendered from the root layout, so a tracker anywhere in it shows.
import { domOracle, gradeConsentGate, openDom } from "../../oracle_dom/oracle_dom.mjs";

await domOracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/layout.tsx", props: { children: "Page body" } });
  if (!dom) return;
  try {
    await gradeConsentGate(t, dom, {
      what: "Hotjar",
      hosts: /^https?:\/\/([a-z0-9-]+\.)*(hotjar\.com|hotjar\.io)\//i,
      marker: /1234567/,
      wiredEval: "typeof window.hj === 'function' || Boolean(window._hjSettings)",
    });
  } finally {
    await dom.close();
  }
});
