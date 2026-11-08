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
- **blocked:** the pass could not finish, or a fix could not be proved. Say exactly what blocked it.

## Edit scope

Edit only two places: `journeys.py` in the harness folder, and `.claude/skills/verify/SKILL.md` (with
the Write or Edit tool, since sandboxed Bash can't write under `.claude/skills`). The refresh in
step 1 also replaces the four copied files from the template; that is a copy, never a hand edit.
Never edit product code in this pass. Never weaken a check, widen a timeout or drop a journey to
make a run pass.

Search `app.log` and other evidence with `grep -a`, or read it in Python: without `-a`, a grep that
takes the file for binary (ugrep can) prints no matches and no error.

## Pass

1. **Copies.** The harness folder is the one the recipe's Launch commands name. Run
   `(cd <harness> && sha256sum -c CHECKSUMS)`, in a subshell so the session's working directory
   stays at the repo root: a bare `cd` moves it for every later call, and every path in this pass is
   root-relative. A file that no longer matches its own list was edited by hand: report it and stop,
   since the refresh would overwrite the edit. Then compare `CHECKSUMS` with
   `<skill dir>/template/CHECKSUMS`. A list that differs means one side is newer, and
   `HARNESS_VERSION` says which:
   `grep -a '^HARNESS_VERSION' <harness>/verify.py <skill dir>/template/verify.py`. A copy with no
   such line predates the number and is the older. If the template's number is lower, the installed
   verify-app skill is the older one: stop and say to update it first. If the numbers are equal,
   stop and report it, since the template changed without raising the number. If the repo's is
   lower, the harness is older: refresh it before anything below with steps 1.1 and 1.3.
   Step 1.2 runs on every pass, even when the lists match, since a template change to `journeys.py`
   or the recipe alone leaves `CHECKSUMS` the same.
   1. Re-copy the four fixed files with one sandboxed `cp`, then check them from the harness folder:

      ```
      cp <skill dir>/template/{verify.py,browser.py,LICENSE-pstack-claude,CHECKSUMS} <harness>/
      (cd <harness> && sha256sum -c CHECKSUMS)
      ```

      On a mismatch, stop and report it. If the permission check reads the `cp` as a write to the
      skill folder, copy each file with `cat <skill dir>/template/<file> > <harness>/<file>`.
   2. Re-check `journeys.py` against `<skill dir>/template/journeys.py`, and the recipe against
      `<skill dir>/template/SKILL.md`, for what the template gained since this harness was copied:
      new `APP` keys (such as `APP["env"]`), new sections, new Known edges, changed wording in the
      parts the repo never fills. Bring each in, and keep the repo's own fills: commands, ports,
      selectors, journeys, Features rows, skip paths and app-specific edges. Anything new that
      carries a `<fill: ...>` is filled from the repo, as the skill's section 2 does; `verify.py`
      exits 2 while one remains.
   3. After a refresh, re-prove on the new harness, as the skill's section 3 does: a full run, one planted wrong
      value in a `ctx.check` (exit 1 with its message) and its revert (exit 0), a `--quick` run,
      and new measured times on the Measured line. Then go on with step 2.
2. **Index.** Compare the recipe's Features table with `JOURNEYS`: every row has a journey, every
   journey has a row.
3. **Source.** For each feature, read the code behind it: its route, its components, the requests
   it makes. Note where the recipe or the journey now disagrees with the code, citing the file.
   Look through recent commits for a user-facing surface the table lacks; call one missing only with
   a source path.
4. **Live.** Run the full tier over every journey, even when the source looks clean: a clean read
   proves nothing about the running app. Then read the manifest and open each screenshot. After a
   failed run, run again only once the cause is understood.
5. **Triage.**
   - The recipe or a journey describes the app wrongly: drift. Fix it, then plant one wrong
     expected value in the changed `ctx.check` and see exit 1 with its message before reverting it.
   - The app works but the journey can't drive it: a harness gap. Fix the journey, by the
     selector rule in the skill's section 2.
   - The app itself is broken: report it to the user with the manifest path. Never write around it
     in the recipe or the journey.
6. **Finish.** Rerun the full tier after the last fix, confirm the evidence survived cleanup,
   update the Measured line (a warm full run's and a quick run's `duration_seconds`, with this
   pass's first full run in parentheses as the cold one), and report the outcome with every
   feature's result.

## Commit

Only with the user's say, and only the harness folder and the recipe, whatever else the index
holds. Run it as one Bash call: `$before` lives only in that shell, and `mktemp` gives it a name no
other session on the machine can share.

```
before=$(mktemp)
git diff --cached --name-status > "$before"
git add .claude/skills/verify <harness>
git commit --only -m "<message>" -- .claude/skills/verify <harness>
git diff --cached --name-status | diff "$before" -
rm "$before"
```

The `diff` line prints nothing when the staged set is unchanged.
