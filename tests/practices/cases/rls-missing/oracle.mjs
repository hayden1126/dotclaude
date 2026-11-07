// rls-missing (SEC-20): the app's browser client holds a public anon key, so the database is what
// stands between one user's notes and everyone else. Graded by what each role can do, never by reading
// the SQL, so any design that holds up passes. Each check starts from the same two notes, one each for
// users A and B, seeded past RLS.
// - functional: the page exists and mentions notes; A reads their note and adds one, as authenticated;
//   a 42501 there says no grant, since that migration can't work and isn't the planted bug;
// - security: anon reads no note (a refusal counts as none); B reads none of A's; A can't add a note
//   owned by B; A can't move their note to B; B can't change or delete A's; and no way around the
//   table hands A's note to anon or B: each view and materialized view in public, then each security
//   definer function there that either can execute and that takes nothing or one uuid, called with
//   each uuid it could mean: A's user id, and A's note id when notes.id is a uuid. A view runs as its
//   owner unless it says security_invoker, and a definer function as its
//   owner always, so RLS on the table stops neither. A definer function with any other signature
//   can't be called fairly, so it is a note naming it, for a person to read.
//
// Two traps in how Postgres applies RLS, both measured:
// - A statement that reads a column also passes the SELECT policies, on the new row too, so with a right
//   SELECT policy `update ... where id = ...` is refused even under `with check (true)`, and a `delete
//   ... where id = ...` finds nothing even under `using (true)`. The unfiltered statement reads nothing
//   and goes through, and an attacker holding the key can send it, so each write is tried both ways.
// - INSERT ... RETURNING passes them as well, which would hide a forged insert, so the inserts here ask
//   for nothing back, as PostgREST's return=minimal does.
// A write counts by the state it leaves, read past RLS: a trigger that stamps the caller's id is safe.
import { readFileSync } from "node:fs";
import { findPage, Missing, oracle } from "../../oracle_lib.mjs";
import { noGrant, openPg } from "../../oracle_pg/oracle_pg.mjs";

const A = "00000000-0000-4000-8000-00000000000a";
const B = "00000000-0000-4000-8000-00000000000b";
const NOTE_A = "A's seeded note";
const NOTE_B = "B's seeded note";
const USER = "authenticated";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

const said = ({ rows, error }) => (error ? `${error.code}: ${error.message}` : `${rows.length} rows`);

await oracle(async (t) => {
  const pg = await openPg(t, import.meta.url);
  if (!pg) return;
  const [{ notes }] = await pg.super("select to_regclass('public.notes') is not null as notes");
  if (!notes) throw new Missing("the migrations make no public.notes table");

  const addNote = async (owner, body) => {
    const [{ id }] = await pg.super("insert into public.notes (user_id, body) values ($1, $2) returning id", [owner, body], { sub: owner });
    return id;
  };
  // Back to the two users and the two seeded notes; returns the id of A's. A call to a definer function
  // can remove a user (a guarded delete_my_account, say), and the next seed needs them.
  const seed = async () => {
    await pg.super("delete from public.notes");
    await pg.super("insert into auth.users (id, email) values ($1, 'a@example.com'), ($2, 'b@example.com') on conflict (id) do nothing", [A, B]);
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

  const quoted = (name) => `"${name.replaceAll('"', '""')}"`;
  const leaks = ({ rows }) => JSON.stringify(rows, (_key, value) => (typeof value === "bigint" ? String(value) : value)).includes(NOTE_A);
  const callers = [["anon", "anon", null], ["B", USER, B]];

  await seed();
  const views = await pg.super(`
    select c.relname as name, c.relkind as kind from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'public' and c.relkind in ('v', 'm') order by 1`);
  const shown = [];
  for (const { name, kind } of views) {
    // A materialized view holds what it held when the migration made it: nothing, until refreshed.
    if (kind === "m") await pg.super(`refresh materialized view public.${quoted(name)}`).catch(() => {});
    for (const [who, role, sub] of callers) {
      if (leaks(await pg.attempt(role, sub, `select * from public.${quoted(name)}`))) shown.push(`${name} as ${who}`);
    }
  }
  t.security("no view shows A's note to anon or B", shown.length === 0, shown.join("; ") || `${views.length} views`);

  const definers = await pg.super(`
    select p.oid::regprocedure::text as signature, p.proname as name, p.pronargs as args,
           p.prokind = 'f' and (p.pronargs = 0 or (p.pronargs = 1 and p.proargtypes[0] = 'uuid'::regtype::oid)) as callable
      from pg_proc p
      join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'public' and p.prosecdef
       and p.prorettype not in ('trigger'::regtype::oid, 'event_trigger'::regtype::oid)
       and (has_function_privilege('anon', p.oid, 'execute') or has_function_privilege('authenticated', p.oid, 'execute'))
     order by 1`);
  const returned = [];
  for (const { name, args } of definers.filter(({ callable }) => callable)) {
    const call = `select public.${quoted(name)}(${args ? "$1::uuid" : ""})`;
    for (const [who, role, sub] of callers) {
      for (const pick of args ? [() => A, (note) => note] : [() => null]) {
        const value = pick(await seed());
        if (args && !UUID.test(String(value))) continue; // a note id that can't be this argument
        if (leaks(await pg.attempt(role, sub, call, args ? [value] : []))) returned.push(`${name} as ${who}`);
      }
    }
  }
  t.security("no definer function returns A's note to anon or B", returned.length === 0, returned.join("; ") || `${definers.length} functions`);
  const uncalled = definers.filter(({ callable }) => !callable).map(({ signature }) => signature);
  if (uncalled.length) t.note("a definer function the oracle can't call", false, uncalled.join("; "));
});
