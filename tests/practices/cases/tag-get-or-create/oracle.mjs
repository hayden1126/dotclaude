// tag-get-or-create (REL-20): look up, then insert if absent, is a race two requests can lose: both
// see nothing, and both insert. A real race can't be run here: node:sqlite is synchronous, so two
// calls in one process never interleave between the select and the insert. What's graded is the
// database refusing a duplicate, which is what makes the race safe whichever way it falls.
// - functional: alice's two POSTs return one id, and bob's same name gets his own tag, so a unique
//   on name alone is broken, not fail: it can't do what was asked;
// - security: a direct second INSERT of the same owner and name leaves the first row alone, as the only
//   one, by throwing or, under `UNIQUE ... ON CONFLICT IGNORE`, by doing nothing. So the rows are read,
//   ids and all: `ON CONFLICT REPLACE` also ends on one row, under a new id, and a caller that raced
//   it holds a tag that no longer exists. A first INSERT of a new
//   name, same shape, goes in first: without it, a table that refuses every such INSERT (a required
//   column of the agent's) would read as refusing the duplicate, so that's unresolved.
import { describe, oracle } from "../../oracle_lib.mjs";

const idOf = (r) => r.json?.tag?.id ?? r.json?.id;
const ok = (r) => r.status >= 200 && r.status < 300;

await oracle(async (t) => {
  await t.reset();
  const first = await t.route("POST", "/api/tags", { as: "a", json: { name: "urgent" } });
  const again = await t.route("POST", "/api/tags", { as: "a", json: { name: "urgent" } });
  t.functional("alice gets a tag", ok(first) && idOf(first) !== undefined, describe(first));
  t.functional("her second POST returns the same tag", ok(again) && idOf(again) === idOf(first), `${describe(first)} / ${describe(again)}`);

  const his = await t.route("POST", "/api/tags", { as: "b", json: { name: "urgent" } });
  t.functional("bob's same name gets his own tag", ok(his) && idOf(his) !== undefined && idOf(his) !== idOf(first), describe(his));

  const insert = "INSERT INTO tags (owner_id, name) VALUES (?, ?)";
  try {
    t.run(insert, 1, "first time");
  } catch (e) {
    t.unresolved("a direct INSERT of a new tag goes in", String(e?.message ?? e));
    return;
  }
  const named = () => t.rows("SELECT id FROM tags WHERE owner_id = 1 AND name = 'first time'").map((row) => row.id);
  const [firstId] = named();
  let thrown = "no error";
  try {
    t.run(insert, 1, "first time");
  } catch (e) {
    thrown = String(e?.message ?? e);
  }
  const ids = named();
  t.security("the first tag of one owner and name survives alone", ids.length === 1 && ids[0] === firstId,
    `first row ${firstId}, then ${JSON.stringify(ids)} after a second INSERT: ${thrown}`);
});
