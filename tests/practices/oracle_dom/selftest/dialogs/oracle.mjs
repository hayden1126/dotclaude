// selftest dialogs: confirm, alert and prompt are answered by the mode the oracle holds, logged
// in dialogs(), and never wedge a click or settle.
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

await oracle(async (t) => {
  const dom = await openDom(t, import.meta.url, { entry: "app/dom/page.tsx" });
  if (!dom) return;
  try {
    await dom.click("#delete");
    t.functional("settle() returns after a dismissed confirm", await dom.settle());
    t.functional("a dismissed confirm sends no action", (await dom.actions()).length === 0, JSON.stringify(await dom.actions()));
    await dom.dialogMode("accept");
    await dom.click("#delete");
    await dom.settle();
    t.functional("an accepted confirm sends one", (await dom.actions()).length === 1, JSON.stringify(await dom.actions()));
    await dom.click("#alert");
    t.functional("settle() returns after an alert", await dom.settle());
    await dom.wait(100); // the alert opens after the page's own 10 ms timer
    t.functional("the page goes on after the alert", (await dom.text("#after")) === "after the alert", await dom.text("#after"));
    await dom.dialogMode("accept", "Ada");
    await dom.click("#prompt");
    await dom.settle();
    t.functional("a prompt gets its text", (await dom.text("#name")) === "Ada", await dom.text("#name"));
    const seen = await dom.dialogs();
    t.functional("dialogs() lists them", seen.filter((d) => d.type === "confirm" && d.message === "Delete this row?").length === 2
      && seen.some((d) => d.type === "alert" && d.message === "Saved") && seen.some((d) => d.type === "prompt"), JSON.stringify(seen));
  } finally {
    await dom.close();
  }
  const mounted = await openDom(t, import.meta.url, { entry: "app/dom/mount/page.tsx", dialogMode: "accept" });
  if (!mounted) return;
  try {
    t.functional("a dialog during mount is answered", (await mounted.text("#answer")) === "true", await mounted.text("#answer"));
  } finally {
    await mounted.close();
  }
});
