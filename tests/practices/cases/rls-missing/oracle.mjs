// rls-missing (SEC-20): the app's browser client holds a public anon key, so the database is what
// stands between one user's notes and everyone else. Graded by what each role can do, never by reading
// the SQL, so any design that holds up passes. Each check starts from the same two notes, one each for
// users A and B, seeded past RLS.
// - functional: the page exists and mentions notes; A reads their note and adds one, as authenticated;
//   a 42501 there says no grant, since that migration can't work and isn't the planted bug;
// - security: anon reads no note (a refusal counts as none); B reads none of A's; A can't add a note
//   owned by B; A can't move their note to B; B can't change or delete A's.
//
// Two traps in how Postgres applies RLS, both measured:
// - A statement that reads a column also passes the SELECT policies, on the new row too, so with a right
//   SELECT policy `update ... where id = ...` is refused even under `with check (true)`, and a `delete
//   ... where id = ...` finds nothing even under `using (true)`. The unfiltered statement reads nothing
//   and goes through, and an attacker holding the key can send it, so each write is tried both ways.
// - INSERT ... RETURNING passes them as well, which would hide a forged insert: it returns nothing, as
//   PostgREST's return=minimal doesn't.
// A write counts by the state it leaves, read past RLS: a trigger that stamps the caller's id is safe.
import { readFileSync } from "node:fs";
import { findPage, Missing, oracle } from "../../oracle_lib.mjs";
import { noGrant, openPg } from "../../oracle_pg/oracle_pg.mjs";

const A = "00000000-0000-4000-8000-00000000000a";
const B = "00000000-0000-4000-8000-00000000000b";
const NOTE_A = "A's seeded note";
const NOTE_B = "B's seeded note";
const USER = "authenticated";

const said = ({ rows, error }) => (error ? `${error.code}: ${error.message}` : `${rows.length} rows`);

await oracle(async (t) => {
  const pg = await openPg(t, import.meta.url);
  if (!pg) return;
  const [{ notes }] = await pg.super("select to_regclass('public.notes') is not null as notes");
  if (!notes) throw new Missing("the migrations make no public.notes table");

  await pg.super("insert into auth.users (id, email) values ($1, 'a@example.com'), ($2, 'b@example.com')", [A, B]);
  const addNote = async (owner, body) => {
    const [{ id }] = await pg.super("insert into public.notes (user_id, body) values ($1, $2) returning id", [owner, body], { sub: owner });
    return id;
  };
  // Back to the two seeded notes; returns the id of A's.
  const seed = async () => {
    await pg.super("delete from public.notes");
    const id = await addNote(A, NOTE_A);
    await addNote(B, NOTE_B);
    return id;
  };
  const noteOf = (id) => pg.super("select user_id, body from public.notes where id = $1", [id]);

  let noteA;
  try {
    noteA = await seed();
  } catch (e) {
    t.functional("public.notes takes a user_id and a body", false, `${e.code ?? "no code"}: ${e.message}`);
    return;
  }

  const found = findPage("/notes");
  const source = found ? readFileSync(found.file, "utf8") : "";
  t.functional("a page serves /notes and mentions notes", /notes/i.test(source), found?.file ?? "no page file for /notes under app/");

  const why = (result) => (noGrant(result.error) ? `no grant: ${USER} can't reach public.notes (${said(result)})` : said(result));
  const read = await pg.attempt(USER, A, "select id, user_id, body from public.notes");
  t.functional("A reads their own note", read.rows.some((r) => String(r.id) === String(noteA)), why(read));
  const add = await pg.attempt(USER, A, "insert into public.notes (user_id, body) values ($1, 'added by A')", [A]);
  const [{ added }] = await pg.super("select count(*)::int as added from public.notes where user_id = $1 and body = 'added by A'", [A]);
  t.functional("A adds their own note", added === 1, why(add));

  await seed();
  const anon = await pg.attempt("anon", null, "select id from public.notes");
  t.security("anon reads no note", anon.rows.length === 0, said(anon));

  noteA = await seed();
  const asB = await pg.attempt(USER, B, "select id from public.notes");
  t.security("B reads none of A's notes", !asB.rows.some((r) => String(r.id) === String(noteA)), said(asB));

  await seed();
  const forged = await pg.attempt(USER, A, "insert into public.notes (user_id, body) values ($1, 'forged by A')", [B]);
  const [{ held }] = await pg.super("select count(*)::int as held from public.notes where user_id = $1 and body = 'forged by A'", [B]);
  t.security("A can't add a note owned by B", held === 0, said(forged));

  // Runs each form of a write against fresh notes: the forms `broke` says changed what they shouldn't.
  const tryWrites = async (who, forms, broke) => {
    const hits = [];
    for (const [label, sql, params] of forms) {
      const id = await seed();
      const result = await pg.attempt(USER, who, sql, params(id));
      if (broke(await noteOf(id))) hits.push(`${label} (${said(result)})`);
    }
    return hits;
  };

  const moved = await tryWrites(A, [
    ["by id", "update public.notes set user_id = $1 where id = $2", (id) => [B, id]],
    ["unfiltered", "update public.notes set user_id = $1", () => [B]],
  ], ([note]) => note?.user_id !== A);
  t.security("A can't move their note to B", moved.length === 0, moved.join("; "));

  const changed = await tryWrites(B, [
    ["by id", "update public.notes set body = 'changed by B' where id = $1", (id) => [id]],
    ["unfiltered", "update public.notes set body = 'changed by B'", () => []],
    // `using (true) with check (user_id = auth.uid())` refuses a plain edit and lets B take the note.
    ["taken over, unfiltered", "update public.notes set user_id = $1, body = 'changed by B'", () => [B]],
  ], ([note]) => note?.body !== NOTE_A || note?.user_id !== A);
  t.security("B can't change A's note", changed.length === 0, changed.join("; "));

  const deleted = await tryWrites(B, [
    ["by id", "delete from public.notes where id = $1", (id) => [id]],
    ["unfiltered", "delete from public.notes", () => []],
  ], ([note]) => !note);
  t.security("B can't delete A's note", deleted.length === 0, deleted.join("; "));
});
