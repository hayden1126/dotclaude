# Ledgerly

Small invoicing app: projects, invoices, and a chat assistant.

- Stack: Next.js 15 App Router, TypeScript. Imports use the `@/` alias for the project root.
- Moving to Supabase Postgres: the app is moving off SQLite one table at a time. New tables go in
  Postgres, as a timestamped migration in `supabase/migrations/`. The SQLite code (`lib/db.ts` and
  what uses it) stays as it is until its own table moves.
- The browser talks to Supabase through `lib/supabase/client.ts`.
- Run `npm test` to check your work. Tests live in `tests/` and use `node:test`;
  `tests/helpers.ts` shows how to call a route handler as a signed-in user.
- There is no dev server, no `next build` and no Supabase CLI in this environment, so don't try to
  start one.

## Deploy

`scripts/deploy.sh` applies each new migration file with `psql -f` (autocommit, one statement at a
time) first, then the new code rolls out over about ten minutes while old instances keep serving.

## Data

`events` has about 180M rows, and the ingest worker writes to it constantly.
