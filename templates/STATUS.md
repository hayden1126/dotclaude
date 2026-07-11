# STATUS: <feature name>

> Living state. Update at the end of every working block so a fresh session can resume from here after `/clear`.
> State each fact once. Git owns push/merge/tree state — derive it (`git status -sb`, `gh pr view`), do not store it here. OPERATIONS.md owns accounts/services; the plan file owns design.

Last updated: <date>
Branch / worktree: <name> (position vs `main`; run git for push/merge state)

## Done
- <task + commit sha>

## In flight
- <current task, what is half-done, next concrete step>

## Blocked / decisions needed
- <blocker or open question, and what would unblock it>

## Notes for next session
- <anything non-obvious to reload: gotchas, where you left off, what to verify next>
