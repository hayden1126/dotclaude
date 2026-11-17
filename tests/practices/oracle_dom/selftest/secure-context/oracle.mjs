// selftest secure-context: the page runs in a secure context, so crypto.randomUUID exists.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    t.functional("the page is a secure context", (await dom.text("#secure")) === "true", await dom.text("#secure"));
    t.functional("crypto.randomUUID works", /^[0-9a-f-]{36}$/.test(await dom.text("#uuid")), await dom.text("#uuid"));
  } finally {
    await dom.close();
  }
});
