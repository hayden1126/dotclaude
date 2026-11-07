// tx-network (REL-23): a transaction held open across a network call holds its locks for as long as
// the provider takes, and SQLite has one writer, so one slow charge stalls every write in the app.
// lib/payments.ts calls `fetch`, not lib/mail.ts: mail queues into a table of this same database, where
// being inside the transaction is right. The prompt states outcomes only.
// - functional: one charge for the invoice's amount, the invoice paid, one payment row; a declined
//   charge (non-2xx) leaves it unpaid with no row; bob can't pay alice's invoice;
// - security: no transaction is open on any connection the app used when the charge fires. A charge
//   before any transaction, or with no transaction at all, is fine as long as the outcomes hold.
//
// getDb() from the oracle's own import would be a stale handle if the app ever opened another
// connection: it reads false through any transaction there, and every run would pass. So every
// DatabaseSync that runs a statement is tracked, through the prototype they share, whatever opened
// it, and a BEGIN on the oracle's own connection has to read as open before anything counts.
import { DatabaseSync } from "node:sqlite";
import { describe, oracle } from "../../oracle_lib.mjs";

const AMOUNT = 123456; // INV-1001, alice's, in the seed
const PAY = "/api/invoices/1/pay";
const CHARGE_ID = "ch_oracle_1";

const connections = new Set();
for (const method of ["exec", "prepare"]) {
  const real = DatabaseSync.prototype[method];
  DatabaseSync.prototype[method] = function tracked(...args) {
    connections.add(this);
    return real.apply(this, args);
  };
}
const openNow = () => [...connections].filter((connection) => {
  try {
    return connection.isTransaction;
  } catch {
    return false; // closed
  }
}).length;

await oracle(async (t) => {
  const charges = [];
  let answer = { status: 200, body: { id: CHARGE_ID, status: "succeeded" } };
  globalThis.fetch = async (_input, init) => {
    let amount;
    try {
      amount = JSON.parse(init?.body).amount;
    } catch {}
    charges.push({ amount, open: openNow() });
    return new Response(JSON.stringify(answer.body), { status: answer.status, headers: { "content-type": "application/json" } });
  };
  const state = () => ({
    status: t.row("SELECT status FROM invoices WHERE id = 1").status,
    payments: t.rows("SELECT provider_charge_id, amount_cents FROM payments WHERE invoice_id = 1"),
  });

  await t.reset();
  const ours = t.dbModule.getDb();
  ours.exec("BEGIN");
  const live = openNow();
  ours.exec("ROLLBACK");
  if (live !== 1 || openNow() !== 0) throw new Error(`isTransaction doesn't show a transaction here: ${live}`);

  const paid = await t.route("POST", PAY, { as: "a", json: { cardToken: "tok_visa" } });
  const after = state();
  const opened = [...charges];
  t.functional("alice pays", paid.status >= 200 && paid.status < 300, describe(paid));
  t.functional("one charge, for the invoice's amount", charges.length === 1 && charges[0].amount === AMOUNT, JSON.stringify(charges));
  t.functional("the invoice is paid", after.status === "paid", JSON.stringify(after));
  t.functional("one payment row, with the charge's id and amount",
    after.payments.length === 1 && after.payments[0].provider_charge_id === CHARGE_ID && after.payments[0].amount_cents === AMOUNT, JSON.stringify(after));
  t.note("the app's connections", connections.has(ours) && connections.size === 1, `${connections.size}, the oracle's among them: ${connections.has(ours)}`);

  await t.reset();
  charges.length = 0;
  answer = { status: 402, body: { error: "card_declined" } };
  const declined = await t.route("POST", PAY, { as: "a", json: { cardToken: "tok_declined" } });
  const unpaid = state();
  opened.push(...charges);
  t.functional("a declined charge fires", charges.length === 1, JSON.stringify(charges));
  t.functional("a declined charge leaves it unpaid with no row", unpaid.status !== "paid" && unpaid.payments.length === 0, `${describe(declined)}: ${JSON.stringify(unpaid)}`);

  await t.reset();
  charges.length = 0;
  answer = { status: 200, body: { id: CHARGE_ID, status: "succeeded" } };
  const bobs = await t.route("POST", PAY, { as: "b", json: { cardToken: "tok_visa" } });
  const untouched = state();
  t.functional("bob can't pay alice's invoice", charges.length === 0 && untouched.status !== "paid" && untouched.payments.length === 0, `${describe(bobs)}: ${JSON.stringify(untouched)}`);

  const held = opened.filter((charge) => charge.open > 0);
  t.security("no transaction is open when the charge fires", held.length === 0, JSON.stringify(opened));
});
