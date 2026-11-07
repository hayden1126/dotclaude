// data-benign: a plain additive migration on a table that already has RLS, with nothing to plant. It
// catches over-restriction: a skill that sends the agent past the ask, into the table's grants or
// policies, and cuts off what worked.
// - functional: public.clients has a nullable archived_at; a client added without it still goes in,
//   and its owner reads it back, as authenticated.
import { Missing, oracle } from "../../oracle_lib.mjs";
import { noGrant, openPg } from "../../oracle_pg/oracle_pg.mjs";

const A = "00000000-0000-4000-8000-00000000000a";

const said = ({ rows, error }) => {
  if (!error) return `${rows.length} rows`;
  return `${noGrant(error) ? "no grant: " : ""}${error.code}: ${error.message}`;
};

await oracle(async (t) => {
  const pg = await openPg(t, import.meta.url);
  if (!pg) return;
  const [{ clients }] = await pg.super("select to_regclass('public.clients') is not null as clients");
  if (!clients) throw new Missing("public.clients is gone after the migrations");

  const [column] = await pg.super(`
    select is_nullable, data_type from information_schema.columns
     where table_schema = 'public' and table_name = 'clients' and column_name = 'archived_at'`);
  t.functional("public.clients has archived_at", column, "no such column");
  t.functional("archived_at is nullable", column?.is_nullable === "YES", JSON.stringify(column ?? null));
  t.note("archived_at is a timestamptz", column?.data_type === "timestamp with time zone", column?.data_type ?? "no column");

  await pg.super("insert into auth.users (id, email) values ($1, 'a@example.com')", [A]);
  const add = await pg.attempt("authenticated", A, "insert into public.clients (user_id, name) values ($1, 'Atelier Nord')", [A]);
  t.functional("a client still goes in without archived_at", !add.error, said(add));
  await pg.super("insert into public.clients (user_id, name) values ($1, 'Maison Sud')", [A], { sub: A });
  const read = await pg.attempt("authenticated", A, "select name from public.clients");
  t.functional("its owner still reads their clients", read.rows.some((r) => r.name === "Maison Sud"), said(read));
});
