# STATUS: <project or feature name>

> Living state. Update at the end of every working block so a fresh session can resume from here after `/clear`.
> State each fact once. Git owns push/merge/tree state — derive it (`git status -sb`, `gh pr view`), do not store it here. OPERATIONS.md owns accounts/services; the plan file owns design.
> Name lanes by id, requests by number and sessions by id, never by words relative to the writer.

Last updated: <date>
Branch / worktree: <name> (position vs `main`; run git for push/merge state)

## Direction
- <what this project is driving at now, and why; the current priority>

## Backlog
- <#request: one line each, queued and not started; the tracker holds the detail>

## Lanes
- Run `lane ls` (board) and `lane ls --requests` (who owns what). Lane state lives in each lane's record; no lanes means this section stays as is.

## Asks
- <what is blocked on Hayden: a design pick, a push or merge approval, a cleanup nod>

## Decisions
- <decision, who made it, date, and a pointer to the evidence (commit, PR #, session id)>

## Blocked
- <blocker or open question, and what would unblock it>

## Notes for next session
- <the exact next step, what to verify, the commit range, and anything non-obvious to reload>
