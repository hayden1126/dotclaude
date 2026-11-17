// selftest consent-labels: which words count as accepting a consent banner, and that a decline
// button never does. A weak word (yes, ok, enable) counts only beside consent wording.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom, consentButton } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.settle();
    const want = await dom.attr("main", "data-expect");
    const button = await consentButton(dom);
    const label = button ? await dom.text(button) : "";
    t.functional(`the accept button is "${want}"`, label === want, label);
  } finally {
    await dom.close();
  }
});
