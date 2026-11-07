---
name: verify-app
description: Write an app repo its own project skill named verify, one command that launches the app, runs a read-only health check, drives it like a user, saves evidence and cleans up, with closed exit codes. Use when asked to set up app verification, to make a change provable on the running app, to create a verify or run skill for a repo, when a repo has no scripted way to prove behaviour, or to audit or refresh an existing verify skill (MAINTAIN.md). Not for unit tests, test mocks or CI config, and not for just running the app once, which the bundled /run does.
---

# Verify-app

Writes `.claude/skills/verify/` into an app repo, from `<skill dir>/template/`. Claude Code's `/run`
reads a project skill whose description covers launching, so it picks this one up, and a project
skill named `verify` is the one Claude is told to run before a commit. What it adds over a plain run
recipe is proof and cleanup: a manifest written at start and finished at the end, closed exit codes,
a token sweep for stray processes, and evidence that survives teardown. A promise the harness can't
keep is worse than no harness, so prove it on the real app before handing it over.

## 1. Interview the repo, not the user

Answer each from the code. Ask the user only what the repo can't tell you.

- **Surface:** what a user touches: web UI, API, CLI. Pick the primary one; note the rest.
- **Run:** the repo's own dev command (package scripts, Makefile, README), its port, env vars, seed
  data and auth. Measure how long it takes to answer.
- **Drive:** an existing harness in the repo wins over `browser.py`. A journey can run a Playwright or
  Cypress spec with `subprocess`; it inherits the run's token, so cleanup still finds it. Otherwise
  use `ctx.page` (headless browser) or `ctx.get` (HTTP).
- **Observe:** what proves a feature worked: page state, a downloaded file, a response body, a log
  line, a written row.
- **Isolate:** what a second instance would collide with: the port, a lock file, a data dir, a
  profile. `preflight` refuses on what the port check can't see.
- **Cost:** what costs money or reaches people: paid APIs, email, SMS, payments, publishing. Those go
  in `FORBIDDEN_REQUESTS`, and no journey goes near them.

If the checkout doesn't start as it is, stop and report exactly what fails. Don't template a repo
that doesn't run: a recipe written against a broken base teaches wrong steps.

## 2. Write the skill

Write into `<repo>/.claude/skills/verify/` with the Write tool: sandboxed Bash can't write under
`.claude/skills`. In a monorepo, use the package that holds the app.

1. Copy `verify.py`, `browser.py`, `LICENSE-pstack-claude` and `CHECKSUMS` from
   `<skill dir>/template/` verbatim. Then, from that folder, run `sha256sum -c CHECKSUMS`. A mismatch
   is a retyping slip: rewrite that file and check again.
2. Fill `journeys.py` and `SKILL.md` from the template, from what the interview found: real commands,
   real selectors, real paths. Replace every `<fill: ...>`; `verify.py` exits 2 while any remain.
   Prefer stable selectors (ids, ARIA labels, data attributes) over position or text.
3. Pick an evidence dir the repo already ignores. Check with `git check-ignore -q <dir>/probe` (exit 0
   means ignored). If none fits, add one line to `.gitignore` and tell the user.

## 3. Prove it once

1. Run `python3 -B .claude/skills/verify/verify.py` from the repo root as one Bash call. Expect exit 0.
2. Read the run's `manifest.json`: `outcome` is `proved`, `port_free_after` is true,
   `processes_left` is empty, every journey `passed`. Note the `dirty` flag.
3. Open the screenshot and look at it: does it show what the journey claims?
4. Plant one wrong expectation in a journey's `ctx.check`, run again and see exit 1 naming that
   check. Revert it and see exit 0 again. A check that can't fail proves nothing.
5. After cleanup, confirm the evidence is still there.
6. Run `--quick` once, and put both measured `duration_seconds` in the recipe.

On any other result, fix the recipe and run again. On exit 3, read `processes_left` and tell the
user; never signal a process marked `outside_repo`.

## 4. Hand over

Report the files written, the tier table, both measured times and the manifest path. Commit or push
nothing without the user's say. When they say commit and the index holds anything else, commit only
the skill:

```
git diff --cached --name-status > "$TMPDIR/staged-before"
git add .claude/skills/verify
git commit --only -m "<message>" -- .claude/skills/verify
git diff --cached --name-status | diff "$TMPDIR/staged-before" -
```

The last line prints nothing when the staged set is unchanged. For upkeep later, follow
`<skill dir>/MAINTAIN.md`.

<!-- Adapts pstack's create-verification-skill and maintain-verification-skill
(github.com/cursor/plugins, plugins/pstack @ 3fe2823, and its feature-map example @ 4612556,
MIT, Copyright (c) 2026 Lauren Tan), via github.com/michael-denyer/pstack-claude @ 79b36d9
(MIT, Copyright (c) 2026 Michael Denyer), text in template/LICENSE-pstack-claude. -->
