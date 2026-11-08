// selftest action-wild: "*" and a RegExp set the mode of an action the oracle can't name, a
// returned {error} comes from actionResults, and a throw with no boundary shows in crashed().
import { oracle } from "../../../oracle_lib.mjs";
import { openDom } from "../../oracle_dom.mjs";

async function goes(t, opts, set, check) {
  const dom = await openDom(t, import.meta.url, opts);
  if (!dom) return;
  try {
    await set?.(dom);
    await dom.click("button");
    await dom.settle();
    await check(dom);
  } finally {
    await dom.close();
  }
}

await oracle(async (t) => {
  const caught = "app/dom/caught/page.tsx";
  const state = "app/dom/state/page.tsx";
  await goes(t, { entry: caught, actionModes: { "*": "fail" } }, null, async (dom) => {
    t.functional('"*" in actionModes fails an agent-named action', (await dom.text("#state")) === "failed", await dom.text("#state"));
  });
  await goes(t, { entry: caught }, (dom) => dom.actionMode("*", "fail"), async (dom) => {
    t.functional('actionMode("*") fails it', (await dom.text("#state")) === "failed", await dom.text("#state"));
  });
  await goes(t, { entry: caught }, (dom) => dom.actionMode(/^archive/, "fail"), async (dom) => {
    t.functional("actionMode(RegExp) fails it", (await dom.text("#state")) === "failed", await dom.text("#state"));
  });
  await goes(t, { entry: caught, actionModes: { "*": "fail", archiveEverything: "ok" } }, null, async (dom) => {
    t.functional("a name's own entry beats the wildcard", (await dom.text("#state")) === "saved", await dom.text("#state"));
  });
  await goes(t, { entry: state, actionResults: { "*": { error: "x" } } }, null, async (dom) => {
    t.functional("a returned error renders", (await dom.text("#error")) === "x", await dom.html());
    t.functional("that page didn't crash", !(await dom.crashed()));
  });
  await goes(t, { entry: state, actionModes: { "*": "fail" } }, null, async (dom) => {
    t.functional("a throw with no boundary shows in crashed()", await dom.crashed(), await dom.html());
  });
});
