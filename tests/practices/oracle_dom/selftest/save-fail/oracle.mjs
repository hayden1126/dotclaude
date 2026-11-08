// selftest save-fail: when the save action fails, the page says so and keeps the typed text.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

const TEXT = "call the printer about the proofs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.actionMode("saveNote", "fail");
    await dom.type("textarea", TEXT);
    t.functional("the note takes typed text", (await dom.value("textarea")) === TEXT, await dom.value("textarea"));
    await dom.click("button");
    await dom.settle();
    const actions = await dom.actions();
    t.functional("Save sends the note", actions.length === 1 && actions[0].args[0] === TEXT, JSON.stringify(actions));
    t.security("a failed save keeps the typed text", (await dom.value("textarea")) === TEXT, `textarea holds ${JSON.stringify(await dom.value("textarea"))}`);
    t.security("a failed save shows an error", await dom.exists("[role=alert]"), (await dom.text("[role=alert]")) ?? "no [role=alert]");
  } finally {
    await dom.close();
  }
});
