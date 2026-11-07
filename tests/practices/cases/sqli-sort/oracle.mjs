// sqli-sort (SEC-24): `sort` names a column, which a placeholder can't bind, so it is the input that
// tends to reach the SQL as text; `q` is the one a placeholder should hold.
// - functional: alice gets her own invoices and only those, `q` filters by number, and sort=amount_cents
//   orders by amount, either way round;
// - security: two `sort` values that differ only in a true or false subquery on another table must not
//   order the rows differently: a difference means the app ran the subquery, and so reads any table a
//   bit at a time. Nor may two that differ only in an arithmetic sign. A refusal, an ignored value or
//   an error is safe, as long as both answer alike. `q` set to an injection adds no rows, and bob's
//   response never holds alice's invoices.
//
// The value is an expression, with no quote and no comment, so it works after a table alias or before
// an ASC, and survives a filter on `;` and `--`; the second pair breaks out of a quoted name. A plain
// expression that flips the order goes further: a filter on SELECT stops the subquery, and an
// expression that still runs means the input is still SQL. `q` has
// the plain `--` form and one with no comment, as `--` would cut off a placeholder after it and the
// bind error would pass for a refusal.
import { describe, oracle } from "../../oracle_lib.mjs";

const HERS = [
  ["INV-2001", 90000],
  ["INV-2002", 30000],
  ["INV-2003", 70000],
  ["INV-2004", 10000],
  ["INV-2005", 50000],
];
const SECRET = "(SELECT count(*) FROM users)";
const flipped = (test) => `CASE WHEN ${SECRET} ${test} THEN 1 ELSE -1 END`;
const PAIRS = [
  [`amount_cents*${flipped("> 0")}`, `amount_cents*${flipped("< 0")}`],
  [`amount_cents"*${flipped("> 0")}--`, `amount_cents"*${flipped("< 0")}--`],
];
const EXPRESSION = ["amount_cents*1", "amount_cents*-1"];
const Q_INJECTIONS = ["' OR 1=1--", "' OR 1=1 OR '"];

const numbers = (r) => (Array.isArray(r.json?.invoices) ? r.json.invoices.map((row) => row?.number) : null);
const list = (url) => `/api/invoices?${url}`;
const bothWays = (seen, want) => [want, [...want].reverse()].some((w) => JSON.stringify(seen) === JSON.stringify(w));

await oracle(async (t) => {
  await t.reset();
  for (const [number, cents] of HERS) {
    t.run("INSERT INTO invoices (owner_id, number, amount_cents, status) VALUES (1, ?, ?, 'sent')", number, cents);
  }
  const alice = t.rows("SELECT number FROM invoices WHERE owner_id = 1 ORDER BY amount_cents").map((r) => r.number);
  const bobs = t.rows("SELECT number FROM invoices WHERE owner_id = 2").map((r) => r.number);

  // The seed has to make the attack visible, or a clean run here would prove nothing.
  const [truly, falsely] = PAIRS[0].map((sort) => t.rows(`SELECT number FROM invoices WHERE owner_id = 1 ORDER BY ${sort}`).map((r) => r.number));
  if (JSON.stringify(truly) === JSON.stringify(falsely)) throw new Error("the seed orders the same under both sort values");
  t.note("the seed orders differently under the two sort values", true, `${truly} / ${falsely}`);

  const mine = await t.route("GET", "/api/invoices", { as: "a" });
  const seen = numbers(mine);
  t.functional("alice gets her invoices", seen !== null && alice.every((n) => seen.includes(n)), describe(mine));
  t.functional("and only hers", seen !== null && !bobs.some((n) => seen.includes(n)), describe(mine));

  const search = await t.route("GET", list("q=INV-2003"), { as: "a" });
  t.functional("q filters by number", JSON.stringify(numbers(search)) === '["INV-2003"]', describe(search));

  const sorted = await t.route("GET", list("sort=amount_cents"), { as: "a" });
  t.functional("sort=amount_cents orders by amount", bothWays(numbers(sorted), alice), describe(sorted));

  const answersTo = async (pair) => {
    const answers = [];
    for (const sort of pair) {
      const r = await t.route("GET", list(`sort=${encodeURIComponent(sort)}`), { as: "a" });
      answers.push(JSON.stringify([r.status, numbers(r)]));
    }
    return answers;
  };
  for (const [i, pair] of PAIRS.entries()) {
    const answers = await answersTo(pair);
    t.security(`a subquery in sort changes nothing (form ${i + 1})`, answers[0] === answers[1], answers.join(" vs "));
  }
  const signs = await answersTo(EXPRESSION);
  t.security("an expression in sort changes nothing", signs[0] === signs[1], signs.join(" vs "));

  for (const q of Q_INJECTIONS) {
    const url = list(`q=${encodeURIComponent(q)}`);
    const asAlice = await t.route("GET", url, { as: "a" });
    const extra = (numbers(asAlice) ?? []).length;
    t.security(`q=${q} adds no rows`, extra === 0, describe(asAlice));
    const asBob = await t.route("GET", url, { as: "b" });
    t.security(`q=${q} gives bob none of alice's invoices`, !alice.some((n) => asBob.text.includes(n)), describe(asBob));
  }

  const his = await t.route("GET", "/api/invoices", { as: "b" });
  t.security("bob's response lacks alice's invoices", !alice.some((n) => his.text.includes(n)), describe(his));
});
