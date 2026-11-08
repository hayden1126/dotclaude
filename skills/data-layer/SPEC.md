# data-layer: spec

The public spec for the `data-layer` skill: what it covers, the rule it enforces, how, why it stays slim, and the public source behind each rule.

## Scope

The skill covers migrations, renames and drops of columns and tables, Row Level Security policies and grants, raw SQL queries, indexes on live tables, and transactions. It owns six rules: REL-31 is enforced, and the other five are lines the skill states and no hook checks. Request handlers belong to `server-code`, and auth flows and sessions to `auth-secrets`.

Files:
- `SKILL.md`: the core rule, the gate rule, the lines nothing enforces, then what to do when the hook stops a migration.
- `events.toml`: REL-31 and the two gate lines for the post-compaction digest, the core one first, since a digest short of room cuts whole lines from the end. It has no event: see the L1 test below.
- Samples for every form REL-31 reads: `tests/setup/practices_samples/data-layer.toml`.

## Core rule

Read how the repo deploys, and unless the repo proves otherwise, build add-then-remove by default and say so in the reply. Never offer it as an option, and never leave it as a risk to decide on.

Why it comes first: a plain rename looks finished. The tests pass, because they run the new code against the new schema, and nothing in the diff shows the old release. The break exists only in the window between the migration and the end of the rollout, so the rule has to start from how the repo deploys.

## Enforcement

| level | what | when |
|---|---|---|
| L0 | The description, written as "Use when" plus concrete triggers, with no workflow summary | the model's choice |
| L2 | REL-31's `when` against the new text an edit writes to a migration path, denied once per file | before the edit lands |
| L2b | REL-31's `command` and `when` against a Bash command's raw text, denied once per matched line | before the command runs |
| L3s | REL-31 on the added lines of a commit's migration files, told to the model | after the commit |
| push | The same scan on what a push would send, denied once per new finding | before the push |
| L4 | The gate lines after a compaction, when the skill was loaded | SessionStart(compact) |

L2b exists because a migration written by a heredoc or `printf` is a Bash call, which L2 never sees. It reads command text only, so it is blunt on purpose: a false match costs one resend, and L3s and push read the commits behind it.

`when` matches line by line. It skips a line that starts with `-- `, `#` or `//`, and otherwise matches anywhere on the line. At the Bash level it reads a literal `\n` or `\t` as the character. It reads these forms, in any case at an edit or a commit. The Bash filter passes SQL in lower, Title or UPPER case and a framework's call as that framework spells it:
- **SQL:** `rename column`, `rename table`, `drop column`, `drop table`, `alter table x rename to y`, `alter table x rename a to b`, `alter table x drop a`, `rename to y` or `rename a to b` alone on the line after `alter table`, with `if exists`, `only`, and schema-qualified or quoted names.
- **T-SQL:** `sp_rename`.
- **Rails:** `rename_column`, `remove_column`, `remove_columns`, `remove_reference`, `remove_belongs_to`, `remove_timestamps`, `rename_table`, `drop_table`, `drop_join_table`, and `t.remove` and `t.rename` in a `change_table` block, with a symbol, or a string after a space. A string in parentheses is a known miss: it reads like `os.remove("x")`.
- **Django:** `RenameField`, `RemoveField`, `RenameModel`, `DeleteModel`, `AlterModelTable`.
- **Alembic:** `op.drop_column`, `op.drop_table`, `op.rename_table`, `new_column_name=`.
- **Knex, TypeORM, Sequelize and Laravel:** `renameColumn`, `renameTable`, `removeColumn`, `dropColumn`, `dropColumns`, `dropTable`, `dropTableIfExists`, `dropIfExists`, `Schema::rename`, `Schema::drop`, and Laravel's column helpers `dropTimestamps`, `dropSoftDeletes` (each with `Tz`), `dropRememberToken`, `dropMorphs`, `dropNullableMorphs` and `dropConstrainedForeignId`.

Never read as a match: `alter column x drop not null`, `alter column x drop default`, `drop constraint`, `rename constraint`, `add column`, `drop index`, `drop trigger`, `drop function`, `drop policy`, or a line that starts with `-- `, `#` or `//`. These leave the old release working, and the first step of an add-then-remove may well say in a comment what a later release drops.

Accepted false matches, each costing one resend: Django's state-only `RemoveField` inside `SeparateDatabaseAndState`, the first step of a drop, a comment after a statement, a `/* */` comment, a `--` with no space after it, an edit of part of a comment, a down migration's drop, `alter index x rename to y`, a temporary table's drop, and at the Bash level a commit message that names a migration and a drop.

## Per-repo layer

- `.claude/practices/data-layer.md`: prose repo rules the skill reads first, such as how the repo deploys or its role names. They win over the defaults.
- `practices-allow: REL-31 <reason>` in the migration passes the rule for that file. Turning the rule off for a dir is `practices-gate`, run by hand.

## Rules

| id | rule | proof | levels | public source |
|---|---|---|---|---|
| REL-31 | Never rename or drop a column or table the old release still reads: add, keep both in sync, remove in a later release. | the old release's queries run against the migrated schema | L2, L2b, L3s, push | [Parallel Change] |
| SEC-20 | Turn on RLS in the same migration as the table, with policies, and grant each role only what it needs as a second layer. | an anonymous client reads no rows, and a role with no grant can't reach the table | none | [Supabase RLS]; [Supabase 45329] |
| SEC-24 | Parameterize every value, and allowlist every identifier (sort column, direction, table name). | a crafted sort value is rejected, and a quote in a value stays data | none | [OWASP SQLi] |
| REL-32 | Build an index on a live table with `CREATE INDEX CONCURRENTLY` outside a transaction, and set `lock_timeout` before DDL that takes a table lock. | writes proceed during the build | none | [Postgres CREATE INDEX]; [Postgres lock_timeout] |
| REL-20 | Enforce uniqueness with a unique index and `ON CONFLICT`, never a select then an insert. | two concurrent requests leave one row | none | [Postgres INSERT] |
| REL-23 | Make no network call inside a transaction: call after the commit, or write an outbox row. | a slow or failed call leaves no lock held and no half-done state | none | [Outbox] |

## Why it is slim

One enforced rule, two gate lines, no event. The five other rules stay as text because a pattern can't judge them well: a missing policy, a query that is safe by construction and a transaction's reach all need context a line of text doesn't hold. A pattern that guessed would deny good code on every run. REL-31 is different: the bad form is a short list of words in a known set of paths, and one deny line carries the whole fix.

## The L1 test

An L1 event denies an edit until the skill is loaded, which costs every session that touches the path a round trip. It is added only when all three hold:
1. A measured failure exists in the eval, on a real case.
2. The bug is an absence that no pattern can see, so an L2 rule can't catch it.
3. The fix needs more than a deny line carries.

REL-31 fails the second and third: a rename is a pattern, and its deny carries the fix.

What would revisit it: a sweep of this skill showing one of the five text-only rules failing on its case (`rls-missing`, `sqli-sort`, `index-live-table`, `tag-get-or-create`, `tx-network`) with the skill available and unloaded, where the rule also passes the second and third tests. A missing RLS policy is the likeliest candidate.

## Unmeasured

- Whether the skill and the deny improve the rename result: this file ships before that run.
- Every framework form but plain SQL. They come from each framework's documentation, not from a run.
- Whether "read how the repo deploys" finds the answer in a repo with no deploy config.

## Sources

- [Parallel Change]: Danilo Sato, Parallel Change (expand, migrate, contract), https://martinfowler.com/bliki/ParallelChange.html
- [Supabase RLS]: Supabase Docs, Row Level Security, https://supabase.com/docs/guides/database/postgres/row-level-security
- [Supabase 45329]: Supabase changelog, Breaking Change: Tables not exposed to Data and GraphQL API automatically (all existing projects on 2026-10-30), https://supabase.com/changelog/45329-breaking-change-tables-not-exposed-to-data-and-graphql-api-automatically
- [OWASP SQLi]: OWASP SQL Injection Prevention Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.html
- [Postgres CREATE INDEX]: PostgreSQL documentation, CREATE INDEX (building indexes concurrently), https://www.postgresql.org/docs/current/sql-createindex.html
- [Postgres lock_timeout]: PostgreSQL documentation, Client Connection Defaults, https://www.postgresql.org/docs/current/runtime-config-client.html
- [Postgres INSERT]: PostgreSQL documentation, INSERT (ON CONFLICT), https://www.postgresql.org/docs/current/sql-insert.html
- [Outbox]: microservices.io, Transactional outbox, https://microservices.io/patterns/data/transactional-outbox.html
