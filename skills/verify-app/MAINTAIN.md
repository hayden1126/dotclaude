# Maintain a verify skill

An upkeep pass for a repo's verify skill, written by this skill: the harness folder
(`scripts/verify/` or `tools/verify/`, named in the recipe's Launch section) and the recipe at
`.claude/skills/verify/SKILL.md`. The app changes and the recipe rots; this pass finds where and
proves the fix. The unit of care is the feature: every feature gets a source read and a live run.

## Outcomes

End with exactly one, and say which:

- **clean:** every feature was read and driven live, and nothing needs changing. No commit.
- **changed:** proven corrections to the verify skill, a refresh from the template included, committed
  only with the user's say.
- **blocked:** the pass stopped in step 1, no full run can be made to pass, or a changed check
  can't be proved. Say exactly what blocked it.

Two terms, used the same way everywhere below:

- **Proved:** a changed `ctx.check` is proved when a planted wrong value fails the run with that
  check's own message, and the revert passes. When the plant run fails for another reason (an
  earlier step timing out), fix that and plant again, as the skill's section 3 does. Edits with no
  check to plant (a refresh's copies, a selector fix, a recipe line) are proved by step 6's final
  runs passing.
- **First run:** the first full run of this pass that got past launch (its manifest has a
  `ready_seconds`). A run refused before launch, such as a held port, doesn't count.

## Edit scope

Edit only two places: `journeys.py` in the harness folder, and `.claude/skills/verify/SKILL.md` (with
the Write or Edit tool, since sandboxed Bash can't write under `.claude/skills`). The refresh in
step 1 also replaces the four copied files from the template; that is a copy, never a hand edit.
Never edit product code in this pass. Never weaken a check, widen a timeout or drop a journey to
make a run pass. Setting `ready_timeout` again from a new measurement, by the skill's section 3 rule,
is not widening: widening is raising it to rescue a failing run with no measurement behind it. The
comment beside `ready_timeout` carries the numbers it came from: the `ready_seconds` measured and the
headroom applied.

Search `app.log` and other evidence with `grep -a`, or read it in Python: without `-a`, a grep that
takes the file for binary (ugrep can) prints no matches and no error.

## Pass

1. **Copies.** The harness folder is the one the recipe's Launch commands name. Run
   `(cd <harness> && sha256sum -c CHECKSUMS)`, in a subshell so the session's working directory
   stays at the repo root: a bare `cd` moves it for every later call, and every path in this pass is
   root-relative. Each stop in this step ends the pass blocked (step 6's first row). A file that no
   longer matches its own list was edited by hand: report it and stop,
   since the refresh would overwrite the edit. Then compare `CHECKSUMS` with
   `<skill dir>/template/CHECKSUMS`. A list that differs means one side is newer, and
   `HARNESS_VERSION` says which:
   `grep -a '^HARNESS_VERSION' <harness>/verify.py <skill dir>/template/verify.py`. A copy with no
   such line predates the number and is the older. If the template's number is lower, the installed
   verify-app skill is the older one: stop and say to update it first. If the numbers are equal,
   stop and report it, since the template changed without raising the number. If the repo's is
   lower, the harness is older: refresh it before anything below, in this order: step 1.1, then
   1.2, then 1.3, since 1.2 edits `journeys.py` and the recipe, and the re-proof has to cover those
   edits. Step 1.2 runs on every pass, even when the lists match, since a template change to
   `journeys.py` or the recipe alone leaves `CHECKSUMS` the same. With no refresh, run step 1.2
   only, then go on with step 2: steps 4 to 6 prove its edits.
   1. Re-copy the four fixed files with one sandboxed `cp`, then check them from the harness folder:

      ```
      cp <skill dir>/template/{verify.py,browser.py,LICENSE-pstack-claude,CHECKSUMS} <harness>/
      (cd <harness> && sha256sum -c CHECKSUMS)
      ```

      On a mismatch, stop and report it, naming the four files already replaced. If the permission check reads the `cp` as a write to the
      skill folder, copy each file with `cat <skill dir>/template/<file> > <harness>/<file>`.
   2. Re-check `journeys.py` against `<skill dir>/template/journeys.py`, and the recipe against
      `<skill dir>/template/SKILL.md`, for what the template gained since this harness was copied:
      new `APP` keys (such as `APP["env"]`), new sections, new Known edges, changed wording in the
      parts the repo never fills (except the Measured line, which step 6 writes whole). Bring each in, and keep the repo's own fills: commands, ports,
      selectors, journeys, Features rows, Not covered rows, skip paths and app-specific edges.
      Anything new that carries a `<fill: ...>` is filled from the repo, as the skill's section 2
      does; `verify.py` exits 2 while one remains. One Known edge per cause: when a template edge
      covers the same cause as a repo edge, merge the two into one. Keep the repo's specific facts
      (paths, counts, file names), take the template's general wording, and drop the duplicate.
   3. After steps 1.1 and 1.2, re-prove on the new harness, as the skill's section 3 does: a full
      run (normally the first run), one planted wrong value in a `ctx.check` (exit 1 with its
      message) and its revert (exit 0), and a `--quick` run. A failed run goes through step 5's
      triage like any other: drift and harness gaps get fixed there. A planted value that still
      won't fail with its own message, after the plant-again rule in Proved, means the new harness
      can't prove anything: blocked. Keep each run's manifest path for
      step 6. When the full run's `app.log` shows reload or rebuild lines (search it with `grep -a`),
      run the skill's section 3 reload check: confirm the trigger with the dev tool's debug output,
      set through `APP["env"]` for one run (for Vite, `{"DEBUG": "vite:hmr"}`), then take the
      setting out again, and move nothing before the trigger is known. Then go on with step 2.
2. **Index.** Compare the recipe's Features table with `JOURNEYS`: every row has a journey, every
   journey has a row.
3. **Source.** For each feature, read the code behind it: its route, its components, the requests
   it makes. Note where the recipe or the journey now disagrees with the code, citing the file.
   Look through recent commits for a user-facing surface the table lacks; call one missing only with
   a source path. When one is missing, add it to the recipe's Not covered list with that path and
   name it in the report. Add a journey for it only with the user's say.
4. **Live.** Run the full tier over every journey, even when the source looks clean: a clean read
   proves nothing about the running app. Then read the manifest and open each screenshot. After a
   failed run, run again only once the cause is understood. With no refresh, this is normally the
   first run, and the same reload check as step 1.3 applies to its `app.log`.
5. **Triage.**
   - The recipe or a journey describes the app wrongly: drift. Fix it, then plant one wrong
     expected value in the changed `ctx.check` and see exit 1 with its message before reverting it.
   - The app works but the journey can't drive it: a harness gap. Fix the journey, by the
     selector rule in the skill's section 2.
   - The app itself is broken: report it to the user with the manifest path; the pass ends blocked.
     Never write around it
     in the recipe or the journey.
   - The app works but logs errors, such as a hydration mismatch: an app warning. Report it to the
     user with the log line from `app.log`, and record it as an app-specific Known edge if it
     recurs across runs. Never fail a run on it, and never hide it: not from the report, and not by
     filtering the log.
6. **Finish.** Ask these in order and stop at the first that applies:
   1. **Clean?** Nothing was edited, the last full run passed, and the skill's section 3 rule
      wouldn't raise `ready_timeout` for the first run's `ready_seconds`. Report every feature's
      result and this pass's times, edit nothing, and stop.
   2. **Blocked?** Step 1 stopped; or no full run can be made to pass (the app is broken, or the
      failure can't be traced); or a changed check can't be proved. Make no more runs, write no
      Measured line, commit nothing. Report what stopped it and its manifest, list every file
      changed or replaced, and stop: the user decides what to keep.
   3. **Changed.** Everything else. In order:
      1. Raise `ready_timeout` if the section 3 rule gives more for the first run's
         `ready_seconds`; never lower it from a run of this pass, which may have been warm.
      2. The final runs: one full run and one `--quick` run on the final files. A failure with a
         new fix to make goes back to step 5. A transient one (a held port) gets one rerun. Any
         other failure is question 2's "no full run can be made to pass": blocked.
      3. Write the Measured line, the only step that writes it, whole: the template's lead-in,
         then the final full run's `duration_seconds`, the first run's in parentheses labelled
         `first`, not `cold` (the dev server's caches may have been warm), then the final quick
         run's. So `full 12.0 (first 29.3), quick 7.7`. This line is the one edit made after the
         final runs.
      4. Report the outcome, every feature's result and every file changed or replaced, then
         commit only with the user's say.

## Commit

Only with the user's say, and only the harness folder and the recipe, whatever else the index
holds. First:

- If the checked-out branch is the repo's default branch and the user hasn't said where to commit,
  ask whether to branch first.
- List what `git add` would take:
  `git status --porcelain --untracked-files=all -- .claude/skills/verify <harness>`. If it lists
  anything beyond the skill's own files (the recipe, `journeys.py` and the four copied files), such
  as a file under a `.claude/.cc-writes/` a sandbox left in the harness folder, stop and ask:
  `git add <harness>` takes every untracked file there.

Run it as one Bash call: `$before` lives only in that shell, and `mktemp` gives it a name no
other session on the machine can share.

```
before=$(mktemp)
git diff --cached --name-status > "$before"
git add .claude/skills/verify <harness>
git commit --only -m "<message>" -- .claude/skills/verify <harness>
git diff --cached --name-status | diff "$before" -
rm "$before"
```

The `diff` line prints nothing when the staged set is unchanged. If `git commit` fails after the
`git add`, stop and report the staged-set diff the `diff` line prints; do not try to undo it.
