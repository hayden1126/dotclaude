---
name: verify-app
description: Write an app repo its own project skill named verify, one command that launches the app, runs a read-only health check, drives it like a user, saves evidence and cleans up, with closed exit codes. Use when asked to set up app verification, to make a change provable on the running app, to create a verify or run skill for a repo, when a repo has no scripted way to prove behaviour, or to audit or refresh an existing verify skill (MAINTAIN.md). Not for unit tests, test mocks or CI config, and not for just running the app once, which the bundled /run does.
---

# Verify-app

Writes an app repo a harness folder and a short `.claude/skills/verify/SKILL.md`, from
`<skill dir>/template/`. Claude Code's `/run` reads a project skill whose description covers
launching, so it picks this one up, and a project skill named `verify` is the one Claude is told to
run before a commit. What it adds over a plain run recipe is proof and cleanup: a manifest written at
start and finished at the end, closed exit codes, a token sweep for stray processes, and evidence
that survives teardown. A promise the harness can't keep is worse than no harness, so prove it on
the real app before handing it over.

## 1. Interview the repo, not the user

Answer each from the code. Ask the user only what the repo can't tell you. Don't start the app by
hand: a server launched outside the harness is a stray process nothing cleans up. The first harness
run (section 3) is the measurement.

- **Surface:** what a user touches: web UI, API, CLI. Pick the primary one; note the rest.
- **Run:** the repo's own dev command (package scripts, Makefile, README), its port, env vars, seed
  data and auth. In a monorepo, the package folder that holds the app.
- **Drive:** an existing harness in the repo wins over `browser.py`. A journey can run a Playwright or
  Cypress spec with `subprocess`; it inherits the run's token, so cleanup still finds it. Otherwise
  use `ctx.page` (headless browser) or `ctx.get` (HTTP).
- **Observe:** what proves a feature worked: page state, a downloaded file, a response body, a log
  line, a written row.
- **Isolate:** what a second instance would collide with: the port, a lock file, a data dir, a
  profile. `preflight` refuses on what the port check can't see.
- **Cost:** what costs money or reaches people: paid APIs, email, SMS, payments, publishing. Those go
  in `FORBIDDEN_REQUESTS`, and no journey goes near them.

## 2. Write the skill

The harness goes in a repo folder, because sandboxed Bash can write there and can't write under
`.claude/skills`: `scripts/verify/` if the repo has a `scripts/` folder at its root, else
`tools/verify/`. If that folder already exists and isn't a verify harness, stop and ask. Only
`SKILL.md` goes in `.claude/skills/verify/`.

1. Copy `verify.py`, `browser.py`, `LICENSE-pstack-claude` and `CHECKSUMS` with one sandboxed `cp`,
   then check them from the harness folder:

   ```
   mkdir -p <harness> && cp <skill dir>/template/{verify.py,browser.py,LICENSE-pstack-claude,CHECKSUMS} <harness>/
   cd <harness> && sha256sum -c CHECKSUMS
   ```

   The check catches a template that drifted from its own list: on a mismatch, stop and report it,
   and edit nothing. If the permission check reads the `cp` as a write to the skill folder, copy
   each file with `cat <skill dir>/template/<file> > <harness>/<file>` instead.
2. Write `<harness>/journeys.py` and `.claude/skills/verify/SKILL.md` from the template's, with the
   Write tool, from what the interview found: real commands, real selectors, real paths. Replace
   every `<fill: ...>`; `verify.py` exits 2 while any remain in either file, and while the recipe is
   missing or empty. `<fill: harness folder>` is the harness path from the repo root, such as
   `tools/verify`. In a monorepo, set `APP["cwd"]` to the app's package folder; `evidence_dir` stays
   relative to the repo root. The recipe's Measured line says `not measured yet`, which is not a
   marker: section 3 replaces it.
3. Selectors: an id, an ARIA label or a data attribute first. A control with none is clicked by its
   visible text with `ctx.page.click_text`, which compares the rendered text: `innerText` with each
   whitespace run collapsed to one space and the ends trimmed, so a button showing a big "A" above
   a small "Single letter" is `"A Single letter"`. Never by position alone, not even with a text
   check.
   Adding attributes to product code is out of scope here: note the gap for the user instead.
4. Before a journey's first click, wait for a sign the client is live with `ctx.page.wait_for`: a
   request the client makes (`performance.getEntriesByName(...)`), or a value only client code
   sets. On a server-rendered page a click before hydration is lost without an error. The
   expression returns a boolean, number or string (`!!el`, not `el`): one returning a DOM node is a
   journey bug, exit 2.
5. Leave `ready_timeout` generous (the template's 300) for the first run, so a slow cold boot is
   measured rather than failed.
6. Pick an evidence dir that is git-ignored and not watched by the dev server. Evidence written
   where the watcher looks sets off reloads that slow the run and flood `app.log`. Prefer a folder
   the dev tool ignores by default: for Vite, `test-results/` (its default watcher skips
   `**/test-results/**`, as Playwright setups do). Otherwise name the watcher config (such as
   `server.watch.ignored` in `vite.config.ts`) and ask the user before changing app config. Check
   git with `git check-ignore -q <dir>/probe` (exit 0 means ignored); if it isn't, add one line to
   `.gitignore` and tell the user.

## 3. Prove it once

1. Run `python3 -B <harness>/verify.py` as one Bash call. It finds the repo root itself (the git top
   level of its folder), so any working folder does. This first run is the launch measurement.
2. If it exits 1 with `ready` false and a `failure` saying the app exited or was never ready (a boot
   crash, or nothing answering by the timeout), stop and report what `app.log` shows: don't template
   a repo that doesn't start, since a recipe written against a broken base teaches wrong steps. A
   doctor row that answers wrongly is the recipe's to fix.
3. Expect exit 0. Read the run's `manifest.json`: `outcome` is `proved`, `port_free_after` is true,
   `processes_left` is empty, every journey `passed`. Note the `dirty` flag and `ready_seconds`.
4. Read the first run's `app.log` for reload or rebuild lines (a page reload, an HMR update, a
   recompile) that start when the journey writes evidence. If there are any, the watcher sees the
   evidence dir: move it by section 2's step 6 and run again.
5. Set `ready_timeout` from the measured `ready_seconds` with headroom (about double, and at least
   30), and say so in a comment beside it.
6. Open the screenshot and look at it: does it show what the journey claims?
7. Plant one wrong expected value in a journey's `ctx.check`, the exact value it compares against
   (not in a `wait_for`, which only times out), run again and see exit 1, with that check's message
   in the manifest. Revert it and see exit 0 again. A check that can't fail proves nothing.
8. After cleanup, confirm the evidence is still there.
9. Run `--quick` once, and replace each `not measured yet` on the recipe's Measured line with the
   measured `duration_seconds` of the full and the quick run.

On any other result, fix the recipe and run again. On exit 3, read `processes_left` and tell the
user; never signal a process marked `outside_repo`.

## 4. Hand over

Report the files written, the paths the recipe lists as skip-safe, both measured times and the
manifest path. Commit or push nothing without the user's say. When they say commit and the index
holds anything else, commit only the skill, its harness and, when section 2 added an ignore line,
`.gitignore`:

```
git diff --cached --name-status > "$TMPDIR/staged-before"
git add .claude/skills/verify <harness> .gitignore
git commit --only -m "<message>" -- .claude/skills/verify <harness> .gitignore
git diff --cached --name-status | diff "$TMPDIR/staged-before" -
```

Drop `.gitignore` from both lines when section 2 left it unchanged. The last line prints nothing
when the staged set is unchanged. For upkeep later, follow
`<skill dir>/MAINTAIN.md`.

<!-- Adapts pstack's create-verification-skill and maintain-verification-skill
(github.com/cursor/plugins, plugins/pstack @ 3fe2823, and its feature-map example @ 4612556,
MIT, Copyright (c) 2026 Lauren Tan), via github.com/michael-denyer/pstack-claude @ 79b36d9
(MIT, Copyright (c) 2026 Michael Denyer), text in template/LICENSE-pstack-claude. -->
