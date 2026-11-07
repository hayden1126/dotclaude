---
name: data-layer
description: Use when writing or changing a migration, renaming or dropping a column or table, adding or changing a Row Level Security policy, or writing a raw SQL query, however small the change. Applies to plain SQL, Supabase, Prisma, Drizzle, Rails, Django, Alembic, Knex and similar.
---

# Data layer

A migration usually runs before the new code is live, and the old release keeps serving until the rollout ends. A plain column rename breaks every old instance the moment it lands, and the tests pass because they run the new code against the new schema. So the schema has to work for the old release and the new one at the same time.

## Core rule: read how the repo deploys, then build add-then-remove

Before a rename or a drop, read how this repo deploys: does the migration run before the new code, and do old instances keep serving during a rollout? The answer is in the CI workflow, the deploy script or the platform's config. Unless the repo proves otherwise, build add-then-remove by default and say so in your reply. Never offer it as an option, and never leave it as a risk for the user to decide on.

Add-then-remove takes two steps:
1. This release: the migration adds the new column, backfills it, and keeps both in sync in the database, since old instances still write only the old one. The new code reads and writes the new column, so the rename the user asked for is done: the migration has already run when that code goes live.
2. A later release, once the old one is gone: remove the old column and the sync. This is the contract step.

When the repo deploys code before migrations, the order flips: the new code has to work before the column exists, so the migration ships a release ahead of it.

Example reply line: "The deploy runs migrations before the new code and old instances keep serving, so I added `handle` beside `username`, with a trigger keeping them equal, and the new code uses `handle`. A later migration removes `username` once this release is the oldest one running."

If `.claude/practices/data-layer.md` exists in the repo, read it first. Its repo rules (how it deploys, its migration tool, its role names) win over the defaults here.

## Gate rule

- **Gate rule REL-31: never rename or drop a column or table the old release still reads.** A rename or drop in a migration ships in the contract step alone, after the old release is gone. A rename without the word COLUMN and a framework's own call (`rename_column`, `RenameField`, `op.drop_column`, `dropColumn`) count too. The engine denies this at the edit and on a Bash command that writes a migration, tells you at the commit, and denies the push.

## Not enforced: do these too

No hook checks these lines. They apply all the same.

- **SEC-20: turn on Row Level Security in the same migration as the table (not enforced).** Write its policies there too, with grants as a second layer: grant each role only what it needs. Grants decide which role reaches the table, and policies decide which rows it sees. A table in an exposed schema with no RLS is open to any role holding a grant. On Supabase a new `public` table gets no grants since 2026-10-30, so a migration that creates a table the API reads has to grant it.
- **SEC-24: parameterize every value, and allowlist every identifier (not enforced).** Never build SQL by concatenating or interpolating input. A sort column, a table name or a direction can't be a parameter, so map the request to a fixed value in code and reject anything else.
- **REL-32: build an index on a live table without blocking writes (not enforced).** Use `CREATE INDEX CONCURRENTLY` outside a transaction. A migration tool usually wraps each file in one, so turn that off for this migration (`disable_ddl_transaction!`, `atomic = False`). Set `lock_timeout` before DDL that takes a table lock, so a waiting `ALTER TABLE` can't hold up every query queued behind it.
- **REL-20: enforce uniqueness in the database (not enforced).** Use a unique index with `ON CONFLICT`, never a select then an insert: two requests can both pass the select.
- **REL-23: make no network call inside a transaction (not enforced).** The call holds the row locks and the connection for as long as the other end takes, and a rollback can't undo it. Do it after the commit, or write an outbox row in the transaction.

## When the hook stops a migration

`[practices:L2:data-layer:REL-31:<path>]` stopped an edit to that migration. `[practices:L2:data-layer:REL-31:bash]` stopped a Bash command, and it read only the command's text. Both mean the text renames or drops something. When this is the first release of the change, rewrite it as add-then-remove and say so. When this is the contract step, check the old release is gone, then resend, or add `practices-allow: REL-31 <reason>` to the migration. A false match (a down migration, a commit message that names a migration and a drop) passes on resend.
