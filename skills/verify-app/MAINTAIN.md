# Maintain a verify skill

An upkeep pass for a repo's `.claude/skills/verify/`, written by this skill. The app changes and the
recipe rots; this pass finds where and proves the fix. The unit of care is the feature: every
feature gets a source read and a live run.

## Outcomes

End with exactly one, and say which:

- **clean:** every feature was read and driven live, and nothing needs changing. No commit.
- **changed:** proven corrections to the verify skill, committed only with the user's say.
- **blocked:** the pass could not finish, or a fix could not be proved. Say exactly what blocked it.

## Edit scope

Edit only the verify skill's folder: `SKILL.md` and `journeys.py`. Never edit product code in this
pass. Never weaken a check, widen a timeout or drop a journey to make a run pass.

## Pass

1. **Copies.** From the verify folder, run `sha256sum -c CHECKSUMS`. Then compare `CHECKSUMS` with
   `<skill dir>/template/CHECKSUMS`. A file that no longer matches its own list was edited by hand:
   report it. A list that differs from the template's is an older harness: copy the template's four
   files in verbatim, check them, and rerun everything below on the new harness.
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
     expectation in the changed check and see exit 1 before reverting it.
   - The app works but the journey can't drive it: a harness gap. Fix the journey.
   - The app itself is broken: report it to the user with the manifest path. Never write around it
     in the recipe or the journey.
6. **Finish.** Rerun the full tier after the last fix, confirm the evidence survived cleanup,
   update the measured times, and report the outcome with every feature's result.
