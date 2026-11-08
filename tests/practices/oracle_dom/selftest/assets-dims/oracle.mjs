// selftest assets-dims: image imports carry their real dimensions (JPEG baseline and
// progressive, WebP lossy and lossless, SVG by width/height or else viewBox), and a JPEG renders
// at that size through next/image.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.settle();
    t.functional("image imports carry their dimensions", (await dom.text("#dims")) === "37x23 37x23 11x7 13x9 40x30 24x16", await dom.text("#dims"));
    const rect = await dom.rect("#photo");
    t.functional("the JPEG renders at its size", rect?.width === 37 && rect?.height === 23, JSON.stringify(rect));
  } finally {
    await dom.close();
  }
});
