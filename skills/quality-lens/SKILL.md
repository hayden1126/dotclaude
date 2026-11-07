---
name: quality-lens
description: A maintainability review of the branch diff, or of the target given, capped at medium severity and advisory only. Runs only when Hayden types its slash command.
disable-model-invocation: true
---

# Quality lens

A second look at structure, once the correctness loop is done. It stays outside that loop:
every lens finding is advisory, and Hayden picks which to fix. A fresh reviewer can always
propose another structure, so these findings must never hold up the until-minor rounds.

Target: `$ARGUMENTS`, or the branch diff against `origin/main` when that is empty.

## Run it

A reviewer has no shell, so write the diff to a file first: `git diff origin/main...HEAD` into
the temp dir. Spawn one `reviewer` with the `delegation` skill's brief, naming that file (or the
target) and the commit, and paste the lens below as its Purpose. Check any finding's command as
that skill's section 3 says, drop what doesn't reproduce, and show Hayden the numbered list.
Change nothing until Hayden picks.

## The lens

This brief asks for maintainability review, so it overrides your rule against it. Review only
what the target adds or changes, and look for:

- a wrapper or helper that only passes through, adding indirection and no clarity;
- a new branch, flag or special case bolted onto a flow it has nothing to do with;
- a cast, optional value or silent fallback hiding an invariant the code could state;
- a helper duplicating a canonical one (name the path of the original);
- feature logic in a shared layer, or a detail leaking across a boundary;
- related updates that can leave state half-applied;
- a simpler structure: a reframing that removes concepts rather than moving them around;
- one file or function doing several jobs.

Each finding must hold up:

- Give path:line and the concrete case: what a future change or reader gets wrong because of it.
- A restructuring names exactly what would disappear (the branches, helpers or lines), and
  says what must keep working. Moving complexity around isn't a finding.
- A size finding names the separate jobs. Line count alone is never a finding.
- Severity is medium or low, never high. A real bug goes in the report as out of the lens's
  scope, for the normal review.
- No taste, no renames, no "consider".

<!-- The lens adapts Cursor's thermo-nuclear-code-quality-review (github.com/cursor/plugins,
MIT, Copyright (c) 2026 Cursor, text in LICENSE-cursor), without its approval bar or its 1k-line
rule. -->
