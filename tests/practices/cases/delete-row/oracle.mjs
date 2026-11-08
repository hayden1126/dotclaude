// UX-63: one click on Delete must not delete. A confirm() or prompt() that was dismissed sends
// nothing; or a confirm step in the page (a modal, or a row that asks again) that sends only when
// pressed; or an undo offered, the action deferred or reversible. An undo window is timed, so
// that path waits it out: wait(), as settle() doesn't see a page's timers.
import { Missing } from "../../oracle_lib.mjs";
import { domOracle, openDom } from "../../oracle_dom/oracle_dom.mjs";

const OPTS = { entry: "app/clients/ClientsTable.tsx", props: { clients: [{ id: 7, name: "Northwind Studio" }, { id: 9, name: "Bluebird Press" }] } };
const DELETE = /delete|remove/i;
const CONFIRM = /confirm|yes|delete|remove/i;
const UNDO_WINDOW_MS = 11000; // past a 10 s toast; the oracle's whole budget is 60 s

const buttons = (dom) => dom.eval(`[...document.querySelectorAll("button, [role=button]")].filter((el) => el.getClientRects().length > 0)
  .map((el) => el.textContent.trim() || el.getAttribute("aria-label") || "")`);
const modalOpen = (dom) => dom.eval(`Boolean(document.querySelector("dialog[open], [role=dialog], [role=alertdialog]"))`);
const undoShown = async (dom) => /\bundo\b/i.test(await dom.eval("document.body.innerText"));

const sent = (actions) => actions.length === 1 && actions[0].name === "deleteClient" && actions[0].args[0] === 7;

// A session clicked into its confirm step: the button that confirms, if any. A button whose words
// are new, inside a modal first; else a matching button when a new Cancel/No sits beside it.
async function confirmButton(dom, before) {
  const seen = new Set(before);
  const fresh = (await buttons(dom)).filter((text) => !seen.has(text));
  const scope = (await modalOpen(dom)) ? "dialog[open] button, [role=dialog] button, [role=alertdialog] button" : "button, [role=button]";
  const exact = fresh.find((text) => CONFIRM.test(text));
  if (exact) return dom.byText(new RegExp(`^\\s*${exact.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*$`, "i"), { tag: scope });
  if (await modalOpen(dom)) return dom.byText(CONFIRM, { tag: scope });
  return fresh.length ? dom.byText(CONFIRM, { tag: scope }) : null;
}

await domOracle(async (t) => {
  const dom = await openDom(t, import.meta.url, OPTS);
  if (!dom) return;
  let needsDialogAccept = false;
  try {
    await dom.settle();
    const del = await dom.byText(DELETE);
    if (!del) throw new Missing("no row has a Delete button");
    const before = await buttons(dom);
    await dom.click(del);
    await dom.settle();
    await dom.wait(200);
    const confirmDialogs = (await dom.dialogs()).filter((d) => d.type !== "alert");
    let actions = await dom.actions();
    if (confirmDialogs.length) {
      t.security("dismissing the dialog sends no action", actions.length === 0, JSON.stringify(actions).slice(0, 300));
      needsDialogAccept = true;
    } else if (actions.length === 0 && await undoShown(dom)) {
      await dom.wait(UNDO_WINDOW_MS);
      actions = await dom.actions();
      t.security("one click offers an undo before the delete lands", true);
      if (sent(actions)) t.functional("the delete reaches the action after the undo window", true);
      else t.unresolved("an undo is offered but no delete arrived inside the window", JSON.stringify(actions));
    } else if (actions.length === 0) {
      const confirm = await confirmButton(dom, before);
      if (!confirm) {
        t.functional("a click on Delete does something", false, "no dialog, no confirm step, no undo and no action");
      } else {
        await dom.click(confirm);
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

  if (!needsDialogAccept) return;
  const accept = await openDom(t, import.meta.url, { ...OPTS, dialogMode: "accept" });
  if (!accept) return;
  try {
    await accept.settle();
    await accept.click(await accept.byText(DELETE));
    await accept.settle();
    await accept.wait(200);
    const actions = await accept.actions();
    t.functional("accepting the dialog sends deleteClient for the row", sent(actions), JSON.stringify(actions).slice(0, 300));
  } finally {
    await accept.close();
  }
});
