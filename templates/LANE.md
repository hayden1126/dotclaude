# LANE: <id>

> This lane's record: only this lane's sessions write it (`lane note` or the Edit tool, from
> inside the lane). Name lanes by id, requests by number, sessions by id. Ownership comes from
> `lane who #<n>`, never from prose here. Derive git and PR state (`lane ls`, `git status -sb`);
> do not store it. Overwrite State and Next at each handoff; do not append recaps.

Branch: <branch> (created <date>)

## Brief
- Goal: <goal>
- Requests: <requests>
- Expected files: <files>
- Overlaps: <overlaps>
- Done when: <done-when>
- Constraints: <constraints>

## State
<!-- Where the work stands: SBAR order (situation, background, assessment). Cite commits by
range (origin/main..<sha>) and PRs by number, not their state. -->

## Decisions
<!-- One line each, with who and the evidence: "Hayden picked X (2026-10-11); evidence:
.lane/artifacts/x.png, session <id>". Promoted into the PR body or memory at merge. -->

## Asks for Hayden
<!-- What this lane is blocked on Hayden for: a design pick, a push or merge approval, a
cleanup nod. Clear a line once answered. `lane asks` lists these across lanes. -->

## Not mine
<!-- Things noticed that belong elsewhere: "#57 looks like lane api-docs's files". Never an
ownership claim for another lane. -->

## Next
<!-- The exact next concrete step and what to verify. handoff-check fails while this is empty. -->
