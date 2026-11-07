// Helpers for the data-layer cases' oracles, the cases with a Supabase overlay (run.py, "PG case").
// A real Postgres (PGlite, WebAssembly, in this process) built to look like a Supabase project, so an
// oracle can test what the agent's migrations do rather than what they say. It lives in this folder so
// the bare PGlite imports resolve from the pinned install here, and apart from oracle_lib.mjs so no
// other case's case_hash moves; only PG cases import it, and only their hash covers it.
//
// It imports nothing from the fixture: the agent's migrations are read as text, once, on load, before
// any agent code runs (oracle() imports lib/ only later), so code loaded for a check can't change them.
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { PGlite } from "@electric-sql/pglite";
import { citext } from "@electric-sql/pglite/contrib/citext";
import { moddatetime } from "@electric-sql/pglite/contrib/moddatetime";
import { pg_trgm } from "@electric-sql/pglite/contrib/pg_trgm";
import { pgcrypto } from "@electric-sql/pglite/contrib/pgcrypto";
import { uuid_ossp } from "@electric-sql/pglite/contrib/uuid_ossp";
import { Missing } from "../oracle_lib.mjs";

const FIXTURE = path.resolve(process.env.FIXTURE ?? ".");
const MIGRATIONS = path.join("supabase", "migrations");
const ROLES = ["anon", "authenticated", "service_role"];

// Supabase's search path: an extension it installs into `extensions` resolves unqualified.
const SESSION = `reset role; reset all; set search_path to "$user", public, extensions;`;

// A Supabase project as an agent's migration finds it. No `alter default privileges` and no grant on
// public tables: since 2026-10-30 a new public table gets no grants to anon, authenticated or
// service_role unless a migration grants them, and a missing grant fails with 42501 before RLS is
// looked at, so a blanket grant here would pass a migration that can't work on the real thing. The
// auth.* bodies are Supabase's: the claims PostgREST sets, and the older per-claim settings.
// pgcrypto and uuid-ossp come enabled on a new project, so `uuid_generate_v4()` works with no line of
// its own, and so does the publication behind Realtime. The other three roles are never graded: a
// migration may name them (a trigger on auth.users).
const BOOTSTRAP = `
create role anon nologin noinherit;
create role authenticated nologin noinherit;
create role service_role nologin noinherit bypassrls;
create role authenticator nologin noinherit;
create role supabase_admin nologin;
create role supabase_auth_admin nologin noinherit;

create schema extensions;
create extension pgcrypto with schema extensions;
create extension "uuid-ossp" with schema extensions;
create publication supabase_realtime;

create schema auth;
create table auth.users (
  id uuid primary key,
  email text unique,
  raw_app_meta_data jsonb,
  raw_user_meta_data jsonb,
  created_at timestamptz not null default now()
);
create function auth.uid() returns uuid language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.sub', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'sub')
  )::uuid
$$;
create function auth.role() returns text language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim.role', true), ''),
    (nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role')
  )::text
$$;
create function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(
    nullif(current_setting('request.jwt.claim', true), ''),
    nullif(current_setting('request.jwt.claims', true), '')
  )::jsonb
$$;

grant usage on schema public, auth, extensions to anon, authenticated, service_role;
grant execute on function auth.uid(), auth.role(), auth.jwt() to anon, authenticated, service_role;
`;

// [{name, sql}] of a dir's *.sql files, in filename order, as the Supabase CLI applies them. Plain
// code-unit order: a locale's order could move a timestamp prefix. No dir reads as no migrations.
function readMigrations(dir) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return [];
  }
  return entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".sql"))
    .map((entry) => entry.name)
    .sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
    .map((name) => ({ name, sql: readFileSync(path.join(dir, name), "utf8") }));
}

const found = readMigrations(path.join(FIXTURE, MIGRATIONS));

const WORD_START = /[A-Za-z_\u0080-\uffff]/;
const WORD_PART = /[\w$\u0080-\uffff]/;
const DOLLAR_TAG = /\$(?:[A-Za-z_\u0080-\uffff][\w\u0080-\uffff]*)?\$/y;

// A script's statements, in order, each without its `;` or any comment before it. `CREATE INDEX
// CONCURRENTLY` runs only outside a transaction, and a multi-statement query is one, so migrations
// can't go to Postgres whole. A `;` ends a statement only outside strings, quoted names, dollar-quoted
// bodies, comments (block comments nest), parentheses (`CREATE RULE ... DO ( a; b )`) and a `BEGIN
// ATOMIC` function body. A `$` inside a name (`a$$b`) opens nothing, and `\'` closes a string only in
// an E'' one. An unterminated quote or comment runs to the end: Postgres then reports it.
export function splitStatements(sql) {
  const statements = [];
  const n = sql.length;
  let i = 0;
  let start = -1; // where the current statement's code began
  let parens = 0;
  let atomic = 0; // BEGIN ATOMIC ... END, with a CASE ... END inside it counted
  let previous = "";

  const skipBlockComment = () => {
    let depth = 0;
    do {
      if (sql.startsWith("/*", i)) {
        depth += 1;
        i += 2;
      } else if (sql.startsWith("*/", i)) {
        depth -= 1;
        i += 2;
      } else i += 1;
    } while (depth > 0 && i < n);
  };
  const skipQuoted = (quote, backslash) => {
    i += 1;
    while (i < n) {
      if (backslash && sql[i] === "\\") i += 2;
      else if (sql[i] !== quote) i += 1;
      else if (sql[i + 1] === quote) i += 2;
      else {
        i += 1;
        return;
      }
    }
  };

  while (i < n) {
    const c = sql[i];
    if (sql.startsWith("--", i)) {
      const end = sql.indexOf("\n", i);
      i = end < 0 ? n : end + 1;
    } else if (sql.startsWith("/*", i)) skipBlockComment();
    else if (/\s/.test(c)) i += 1;
    else if (c === ";" && parens === 0 && atomic === 0) {
      if (start >= 0) statements.push(sql.slice(start, i).trim());
      start = -1;
      previous = "";
      i += 1;
    } else {
      if (start < 0) start = i;
      if (c === "'" || c === '"') skipQuoted(c, false);
      else if (c === "$") {
        DOLLAR_TAG.lastIndex = i;
        const tag = DOLLAR_TAG.exec(sql)?.[0];
        if (tag) {
          const close = sql.indexOf(tag, i + tag.length);
          i = close < 0 ? n : close + tag.length;
        } else i += 1;
      } else if (WORD_START.test(c)) {
        const from = i;
        while (i < n && WORD_PART.test(sql[i])) i += 1;
        const word = sql.slice(from, i).toLowerCase();
        if (word === "e" && sql[i] === "'") skipQuoted("'", true);
        else if (previous === "begin" && word === "atomic") atomic = 1;
        else if (atomic && word === "case") atomic += 1;
        else if (atomic && word === "end") atomic -= 1;
        previous = word;
      } else {
        if (c === "(") parens += 1;
        else if (c === ")") parens = Math.max(0, parens - 1);
        i += 1;
      }
    }
  }
  if (start >= 0) statements.push(sql.slice(start).trim());
  return statements;
}

const clip = (text, length = 400) => (text.length > length ? `${text.slice(0, length)}...` : text);
const failure = (e) => ({ code: e?.code ?? null, message: String(e?.message ?? e) });

// Whether an error is the missing-grant 42501 and not RLS's: "new row violates row-level security
// policy" carries the same code, and means the grant is there.
export const noGrant = (error) => error?.code === "42501" && /^permission denied/.test(error.message);

export class Pg {
  async boot() {
    this.db = new PGlite({ extensions: { citext, moddatetime, pg_trgm, pgcrypto, uuid_ossp } });
    await this.db.waitReady;
    await this.db.exec(BOOTSTRAP);
    await this.db.exec(SESSION);
    return this;
  }

  // Applies `files` one statement at a time: {ok: true}, or the first failure as {detail}, with
  // `extension` set when what's missing is an extension PGlite doesn't have. Each file ends as a
  // connection does: an open transaction rolls back, and a `set` in it stops applying.
  async migrate(files) {
    for (const { name, sql } of files) {
      for (const statement of splitStatements(sql)) {
        try {
          await this.db.exec(statement);
        } catch (e) {
          // A bare `create extension pgcrypto`: Supabase has it on already, and that's what was asked.
          if (e.code === "42710" && /^extension /.test(e.message)) continue;
          return {
            ok: false,
            extension: e.code === "0A000" && /^extension .* is not available/.test(e.message),
            detail: `${name}: ${e.code ?? "no code"} ${e.message}: ${clip(statement)}`,
          };
        }
      }
      if (this.db.isInTransaction()) await this.db.exec("rollback");
      await this.db.exec(SESSION);
    }
    return { ok: true };
  }

  // Sets the claims PostgREST sets for a request. Empty claims read as none (the shims' nullif).
  async setClaims(claims) {
    await this.db.query("select set_config('request.jwt.claims', $1, false)", [claims ? JSON.stringify(claims) : ""]);
  }

  // Runs `sql` as the superuser that owns everything, past RLS: rows. `sub` sets the claims while it
  // does, so a trigger that stamps auth.uid() on a row gets its owner, not null.
  async super(sql, params = [], { sub } = {}) {
    if (sub) await this.setClaims({ sub, role: "authenticated" });
    try {
      return (await this.db.query(sql, params)).rows;
    } finally {
      if (sub) await this.setClaims(null);
    }
  }

  // Runs fn() as `role`, with the claims of user `sub` (none for anon), as a request through PostgREST
  // does. Whatever fn() does, by any exit, the session is back to the superuser with no claims.
  async asUser(role, sub, fn) {
    if (!ROLES.includes(role)) throw new Error(`unknown role ${role}`);
    try {
      await this.setClaims({ role, aud: role, ...(sub ? { sub } : {}) });
      await this.db.exec(`set role ${role}`);
      return await fn(this.db);
    } finally {
      if (this.db.isInTransaction()) await this.db.exec("rollback");
      await this.db.exec("reset role");
      await this.setClaims(null);
    }
  }

  // One statement through asUser: {rows, error}, a refusal being an answer here, never a throw.
  async attempt(role, sub, sql, params = []) {
    try {
      return { rows: (await this.asUser(role, sub, (db) => db.query(sql, params))).rows, error: null };
    } catch (e) {
      return { rows: [], error: failure(e) };
    }
  }
}

// The Postgres for the oracle at `oracleUrl` (its import.meta.url), with the fixture's migrations
// applied, or null when the verdict is already in. A migration counts as the agent's when its name or
// its bytes differ from the case's pristine setup/ overlay, so an edited baseline file counts and an
// untouched one doesn't. None of those is Missing. A failed statement scores broken, naming the file
// and the statement; an extension PGlite lacks scores unresolved, since nothing was observed about
// the migration past it.
export async function openPg(t, oracleUrl) {
  const baseline = new Map(readMigrations(path.join(path.dirname(fileURLToPath(oracleUrl)), "setup", MIGRATIONS)).map(({ name, sql }) => [name, sql]));
  const added = found.filter(({ name, sql }) => baseline.get(name) !== sql).map(({ name }) => name);
  if (!added.length) throw new Missing(`no migration added under ${MIGRATIONS}`);
  const pg = await new Pg().boot();
  const result = await pg.migrate(found);
  if (result.ok) {
    t.functional("the migrations apply", true, added.join(", "));
    return pg;
  }
  if (result.extension) {
    t.functional("the migrations apply up to an extension PGlite lacks", true, added.join(", "));
    t.unresolved("a migration needs an extension PGlite lacks", result.detail);
  } else t.functional("the migrations apply", false, result.detail);
  return null;
}
