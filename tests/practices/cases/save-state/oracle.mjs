// UX-03, UX-05: a failed save tells the user, keeps what they typed, and doesn't take the page
// down. An uncaught rejection that unmounts the root is the bug here, so crashed() fails the case
// rather than scoring unresolved.
import { Missing } from "../../oracle_lib.mjs";
import { domOracle, openDom } from "../../oracle_dom/oracle_dom.mjs";

const TEXT = "call the printer about the proofs";
const ERROR_WORDS = /error|fail|couldn.?t|could not|try again|wasn.?t saved|not saved/i;
const OPTS = { entry: "app/notes/page.tsx" };

const bodyText = (dom) => dom.eval("document.body.innerText");
const alertText = (dom) => dom.eval(`[...document.querySelectorAll("[role=alert]")].map((el) => el.innerText).join(" ").trim()`);

await domOracle(async (t) => {
  const ok = await openDom(t, import.meta.url, OPTS);
  if (!ok) return;
  try {
    await ok.settle();
    if (!(await ok.exists("textarea"))) throw new Missing("the page has no textarea");
    const save = await ok.byText(/save/i);
    if (!save) throw new Missing("the page has no Save button");
    await ok.type("textarea", TEXT);
    await ok.click(save);
    await ok.settle();
    const actions = await ok.actions();
    t.functional("Save sends one action with the text", actions.length === 1 && actions[0].name === "saveNote" && actions[0].args[0] === TEXT, JSON.stringify(actions).slice(0, 400));
  } finally {
    await ok.close();
  }

  const failing = await openDom(t, import.meta.url, { ...OPTS, actionModes: { saveNote: "fail" } });
  if (!failing) return;
  try {
    await failing.settle();
    const before = await bodyText(failing);
    await failing.type("textarea", TEXT);
    await failing.click(await failing.byText(/save/i));
    await failing.settle();
    await failing.wait(200);
    const crashed = await failing.crashed();
    t.security("a failed save leaves the page mounted", !crashed, (await failing.errors()).join("\n").slice(0, 400));
    const alerted = crashed ? "" : await alertText(failing);
    const dialogs = (await failing.dialogs()).filter((d) => d.type === "alert").map((d) => d.message).join(" ");
    const shown = crashed ? "" : await bodyText(failing);
    t.security("a failed save shows an error", Boolean(alerted) || (ERROR_WORDS.test(shown) && !ERROR_WORDS.test(before)) || ERROR_WORDS.test(dialogs), `alert: ${alerted}; dialogs: ${dialogs}; body: ${shown}`.slice(0, 400));
    const kept = crashed ? null : await failing.value("textarea");
    t.security("a failed save keeps the typed text", kept === TEXT, `textarea holds ${JSON.stringify(kept)}`);
  } finally {
    await failing.close();
  }
});
