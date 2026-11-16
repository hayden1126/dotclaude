// selftest stall-after-mount: Chrome itself stops answering partway through an oracle body (here
// stopped with SIGSTOP), which isn't the agent's doing: domOracle scores it unresolved.
import { domOracle, openDom } from "../../oracle_dom.mjs";

await domOracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    process.kill(dom.chrome.child.pid, "SIGSTOP");
    await dom.click("#hello");
    t.functional("never reached", false);
  } finally {
    await dom.close();
  }
});
