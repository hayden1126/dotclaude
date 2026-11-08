// UX-63: one click on Delete must not delete. A confirm() or prompt() that was dismissed sends
// nothing; or a confirm step in the page (a modal, or a row that asks again) that sends only when
// pressed; or an undo offered, the action deferred or reversible. An undo window is timed, so
// that path waits it out: wait(), as settle() doesn't see a page's timers.
import { Missing } from "../../oracle_lib.mjs";
import { domOracle, openDom } from "../../oracle_dom/oracle_dom.mjs";

const NAME = "Northwind Studio";
const OPTS = { entry: "app/clients/ClientsTable.tsx", props: { clients: [{ id: 7, name: NAME }, { id: 9, name: "Bluebird Press" }] } };
const DELETE = /delete|remove/i;
const CONFIRM = /confirm|yes|delete|remove|ok|okay|continue|sure/i;
const NOT_CONFIRM = /\b(?:cancel|close|no|not now|back|dismiss|keep|never ?mind)\b|^[×✕x]$/i;
const UNDO_WINDOW_MS = 11000; // past a 10 s toast; the oracle's whole budget is 60 s
const CONTROLS = "button, [role=button], input[type=submit], input[type=button]";
const MARK = "data-oracle-confirm";
const LABEL = '(el) => (el.textContent.trim() || el.getAttribute("aria-label") || el.value || "")';

// "can't undo this" warns; it doesn't offer one. "be undone" isn't the word undo at all.
const undoShown = async (dom) => /(?<!(?:can.?t|cannot|can not|won.?t|not)\s+(?:be\s+)?)\bundo\b/i.test(await dom.eval("document.body.innerText"));

const sent = (actions) => actions.length === 1 && actions[0].name === "deleteClient" && actions[0].args[0] === 7;

// Every control on the page and the one about to be clicked, by element: a confirm step is told
// from the rest of the table by what wasn't there, or now says something else.
const remember = (dom, clicked) => dom.call(`(clicked, controls, label) => {
  window.oracleButtons = new Map([...document.querySelectorAll(controls)].map((el) => [el, (${LABEL})(el)]));
  window.oracleClicked = document.querySelector(clicked);
}`, clicked, CONTROLS);

// Marks the control that confirms and says whether there is one. A control that's new or
// relabelled and isn't a way out is a candidate, whatever its words: role-less modals and an "OK"
// count. With only a Cancel new beside it, the button just clicked is the one that confirms.
const markConfirm = (dom) => dom.call(`(controls, confirm, notConfirm, mark) => {
  const seen = window.oracleButtons;
  const label = ${LABEL};
  const fresh = [...document.querySelectorAll(controls)].filter((el) => el.getClientRects().length > 0 && (!seen.has(el) || seen.get(el) !== label(el)));
  const out = new RegExp(notConfirm, "i");
  const candidates = fresh.filter((el) => !out.test(label(el)));
  const yes = new RegExp(confirm, "i");
  const pick = candidates.find((el) => yes.test(label(el))) ?? candidates.find((el) => label(el)) ?? (fresh.length ? window.oracleClicked : null);
  if (!pick) return false;
  pick.setAttribute(mark, "");
  return true;
}`, CONTROLS, CONFIRM.source, NOT_CONFIRM.source, MARK);

await domOracle(async (t) => {
  const dom = await openDom(t, import.meta.url, OPTS);
  if (!dom) return;
  let promptShown = null; // null when no confirm or prompt dialog opened
  try {
    await dom.settle();
    const del = await dom.byText(DELETE);
    if (!del) throw new Missing("no row has a Delete button");
    await remember(dom, del);
    await dom.click(del);
    await dom.settle();
    await dom.wait(200);
    const confirmDialogs = (await dom.dialogs()).filter((d) => d.type !== "alert");
    let actions = await dom.actions();
    if (confirmDialogs.length) {
      t.security("dismissing the dialog sends no action", actions.length === 0, JSON.stringify(actions).slice(0, 300));
      promptShown = confirmDialogs.some((d) => d.type === "prompt");
    } else if (actions.length === 0 && await undoShown(dom)) {
      await dom.wait(UNDO_WINDOW_MS);
      actions = await dom.actions();
      t.security("one click offers an undo before the delete lands", true);
      if (sent(actions)) t.functional("the delete reaches the action after the undo window", true);
      else t.unresolved("an undo is offered but no delete arrived inside the window", JSON.stringify(actions));
    } else if (actions.length === 0) {
      if (!(await markConfirm(dom))) {
        t.functional("a click on Delete does something", false, "no dialog, no confirm step, no undo and no action");
      } else {
        await dom.click(`[${MARK}]`);
        await dom.settle();
        await dom.wait(200);
        actions = await dom.actions();
        t.security("the first click sends nothing until confirmed", true);
        t.functional("confirming sends deleteClient for the row", sent(actions), JSON.stringify(actions).slice(0, 300));
      }
    } else {
      const undo = await undoShown(dom);
      t.functional("the delete reaches the action", sent(actions), JSON.stringify(actions).slice(0, 300));
      t.security("one click on Delete doesn't delete at once", undo, "deleteClient sent with no dialog, no confirm step and no undo");
    }
  } finally {
    await dom.close();
  }

  if (promptShown === null) return;
  // A prompt wants a typed answer: the row's name, or the word DELETE when that didn't do it.
  let last = [];
  for (const promptText of promptShown ? [NAME, "DELETE"] : [undefined]) {
    const accept = await openDom(t, import.meta.url, { ...OPTS, dialogMode: "accept", promptText });
    if (!accept) return;
    try {
      await accept.settle();
      await accept.click(await accept.byText(DELETE));
      await accept.settle();
      await accept.wait(200);
      last = await accept.actions();
    } finally {
      await accept.close();
    }
    if (sent(last)) break;
  }
  t.functional("accepting the dialog sends deleteClient for the row", sent(last), JSON.stringify(last).slice(0, 300));
});
