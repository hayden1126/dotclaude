// index-live-table (REL-32): the project notes say events is large and written to all the time, and
// a plain CREATE INDEX holds off every write for the whole build. Locks can't be raced on PGlite's one
// connection, so the build's form is read from the SQL, the one verdict here that reads it.
// - functional: a valid index whose leading column is client_id is on public.events, read from the
//   catalog; a concurrent build inside a transaction refuses with 25001, so it never gets here;
// - security: no `create [unique] index` on public.events among the agent's statements lacks
//   CONCURRENTLY. lock_timeout is a note: a good idea, and not the rule.
//
// Statements come from splitStatements and their words from codeTokens, so a word in a comment or a
// string can't decide it. An index on client_id with no create index statement behind it came from
// something the oracle doesn't read (a DO block, a unique constraint): that's unresolved, never a pass.
import { oracle } from "../../oracle_lib.mjs";
import { codeTokens, openPg, splitStatements } from "../../oracle_pg/oracle_pg.mjs";

// {schema, table, concurrently} of a `create [unique] index` statement, else null.
function indexBuild(statement) {
  const tokens = codeTokens(statement);
  const word = (i, text) => tokens[i]?.kind === "word" && tokens[i].text === text;
  let i = 0;
  if (!word(i++, "create")) return null;
  if (word(i, "unique")) i += 1;
  if (!word(i++, "index")) return null;
  const concurrently = word(i, "concurrently");
  while (i < tokens.length && !word(i, "on")) i += 1;
  i += word(i + 1, "only") ? 2 : 1;
  const names = [tokens[i]?.text];
  while (tokens[i + 1]?.text === "." && tokens[i + 1].kind === "punct") {
    i += 2;
    names.push(tokens[i]?.text);
  }
  return { schema: names.length > 1 ? names.at(-2) : "public", table: names.at(-1), concurrently };
}

await oracle(async (t) => {
  const pg = await openPg(t, import.meta.url);
  if (!pg) return;

  const indexes = await pg.super(`
    select c.relname as name, i.indisvalid as valid
      from pg_index i
      join pg_class c on c.oid = i.indexrelid
      join pg_class tbl on tbl.oid = i.indrelid
      join pg_namespace n on n.oid = tbl.relnamespace
      join pg_attribute a on a.attrelid = i.indrelid and a.attnum = i.indkey[0]
     where n.nspname = 'public' and tbl.relname = 'events' and a.attname = 'client_id'`);
  t.functional("a valid index leads with client_id on public.events", indexes.some((index) => index.valid), JSON.stringify(indexes));

  const statements = pg.added.flatMap(({ name, sql }) => splitStatements(sql).map((statement) => ({ name, statement })));
  const builds = statements
    .map(({ name, statement }) => ({ name, statement, build: indexBuild(statement) }))
    .filter(({ build }) => build?.table === "events" && build.schema === "public");
  const plain = builds.filter(({ build }) => !build.concurrently);
  t.security("every index on public.events builds concurrently", plain.length === 0,
    plain.map(({ name, statement }) => `${name}: ${statement}`).join("; ") || `${builds.length} concurrent`);
  if (!builds.length) t.unresolved("nothing the oracle reads made the index", "no create index statement on public.events, and the catalog has one: read the migration");

  const timeout = statements.some(({ statement }) => codeTokens(statement).some((token) => token.text === "lock_timeout"));
  t.note("the migration sets lock_timeout", timeout);
});
