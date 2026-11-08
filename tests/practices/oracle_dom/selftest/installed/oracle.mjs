// selftest installed: packages in the fixture's node_modules are bundled from there. A CJS main,
// an ESM exports map with a browser condition and a subpath, a package's own bare dependency, a
// browser field that swaps a file and blanks a builtin. One that can't be bundled or throws as it
// loads scores unresolved; an import of a package neither installed nor declared stays Missing.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    for (const [id, want] of [["cjs", "cjs:helper"], ["esm", "esm:browser"], ["sub", "sub"], ["dep", "cjs:helper"], ["map", "swapped:no-builtin"]]) {
      t.functional(`#${id} reads ${want}`, (await dom.text(`#${id}`)) === want, await dom.text(`#${id}`));
    }
  } finally {
    await dom.close();
  }
});
