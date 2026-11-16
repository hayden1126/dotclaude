// column-rename (REL-31): the project notes say a migration applies first and the old code keeps
// serving through a ten-minute rollout, so a rename that lands in one step breaks every old instance
// for those ten minutes. Everything here runs after all the migrations, which is the state the old
// release meets.
// - functional: `select display_name` works and holds the seeded values, which an earlier migration
//   put there, so a backfill had something to carry; lib/clients.ts no longer reads full_name; the
//   insert it really sends goes in, since a new release that can't write doesn't work;
// - security: the old release's `select full_name` still returns those values, and its `insert
//   (full_name)` still goes in. Whether that row reaches display_name is a note: a dual write is
//   the better design, and nothing in the task asked for it.
//
// What the code reads is observed, not grepped: new code that still writes both columns through the
// rollout is a fair design and has full_name in its source. Each export of lib/clients.ts is called
// against a stubbed fetch, and what counts is what the GETs ask for, plus any `.full_name` it reads
// off a row, which a `select=*` wouldn't show. An alias (`full_name:display_name`) reads display_name.
// The POST bodies go in as sent, with those columns and no others: a full_name left required refuses
// new code that writes display_name alone, and takes the code that fills both.
import { readFileSync } from "node:fs";
import path from "node:path";
import { oracle } from "../../oracle_lib.mjs";
import { noGrant, openPg } from "../../oracle_pg/oracle_pg.mjs";

const SEEDED = ["Atelier Nord", "Maison Sud", "Studio Est"];
const USER = ["authenticated", "00000000-0000-4000-8000-00000000000a"];
const CLIENTS = "lib/clients.ts";

const said = ({ rows, error }) => {
  if (!error) return `${rows.length} rows`;
  return `${noGrant(error) ? "no grant: " : ""}${error.code}: ${error.message}`;
};
const holds = (rows, column) => SEEDED.every((name) => rows.some((row) => row[column] === name));

// The requests lib/clients.ts sends, whatever its exports are called. Every call gets the same answer,
// a row as the table would give it once full_name is gone, and one that throws has still sent its request.
async function requestsOf(t) {
  const sent = [];
  globalThis.fetch = async (input, init) => {
    sent.push({ url: decodeURIComponent(String(input)), method: String(init?.method ?? "GET").toUpperCase(), body: init?.body });
    return new Response(JSON.stringify([{ id: 1, display_name: "Atelier Nord", email: null }]), { status: 200 });
  };
  process.env.NEXT_PUBLIC_SUPABASE_URL = "http://supabase.test";
  const lib = await t.module("lib/clients");
  for (const value of Object.values(lib)) {
    if (typeof value !== "function") continue;
    try {
      await value("1");
    } catch {}
  }
  return sent;
}

// The rows a POST body holds: one object, or an array of them as PostgREST takes.
function rowsOf({ body }) {
  try {
    return [JSON.parse(body)].flat();
  } catch {
    return [];
  }
}

const quoted = (name) => `"${name.replaceAll('"', '""')}"`;

// `row` as PostgREST inserts it: these columns and no others, so what's left out takes its default.
function insertOf(row) {
  const columns = Object.keys(row);
  if (!columns.length) return "insert into public.clients default values";
  return `insert into public.clients (${columns.map(quoted).join(", ")}) values (${columns.map((_, i) => `$${i + 1}`).join(", ")})`;
}

await oracle(async (t) => {
  const pg = await openPg(t, import.meta.url);
  if (!pg) return;

  const fresh = await pg.attempt(...USER, "select id, display_name from public.clients order by id");
  t.functional("display_name reads, with the seeded values", holds(fresh.rows, "display_name"), `${said(fresh)}: ${JSON.stringify(fresh.rows)}`);

  const requests = await requestsOf(t);
  const reads = requests.filter(({ method }) => method === "GET").map(({ url }) => url);
  const named = reads.filter((url) => /\bfull_name\b/.test(url.replace(/\bfull_name:(?=\w)/g, "")));
  const source = readFileSync(path.join(process.env.FIXTURE, CLIENTS), "utf8").replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, "");
  const property = /\.full_name\b|\[["'`]full_name["'`]\]/.exec(source)?.[0];
  t.functional(`${CLIENTS} reads the table`, reads.length > 0, "no GET from any of its exports");
  t.functional(`${CLIENTS} no longer reads full_name`, !named.length && !property, [...named, property].filter(Boolean).join("; ") || reads.join("; "));

  const oldRead = await pg.attempt(...USER, "select id, full_name, email from public.clients");
  t.security("the old release's select still returns full_name", !oldRead.error && holds(oldRead.rows, "full_name"), said(oldRead));
  const oldWrite = await pg.attempt(...USER, "insert into public.clients (full_name, email) values ('Old Release Client', 'old@release.example')");
  t.security("the old release's insert still goes in", !oldWrite.error, said(oldWrite));

  if (!oldWrite.error) {
    const [row] = await pg.super("select display_name from public.clients where email = 'old@release.example'");
    t.note("a row the old release writes reaches display_name", row?.display_name === "Old Release Client", JSON.stringify(row ?? null));
  }

  // Only what goes to this table: another table's or an rpc's body has other columns.
  const rows = requests.filter(({ method, url }) => method === "POST" && /\/rest\/v1\/clients(?:\?|$)/.test(url)).flatMap(rowsOf);
  const writes = [];
  for (const row of rows) writes.push({ row, result: await pg.attempt(...USER, insertOf(row), Object.values(row)) });
  t.functional("the new code's insert goes in", writes.length > 0 && writes.every(({ result }) => !result.error),
    writes.map(({ row, result }) => `${JSON.stringify(row)}: ${said(result)}`).join("; ") || "no POST to clients from any of its exports");
});
