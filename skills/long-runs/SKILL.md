---
name: long-runs
description: Use when about to start, plan or rerun a long or multi-part job (test suites, gates, a browser sweep, an eval matrix, a release check, a CI pipeline), when offering a lighter set of checks or a time cost, when asked why a run or CI is slow, when deciding what must rerun after a rebase or small change, or when writing up which checks ran or were skipped. Not for one quick command.
---

# Long runs

A job takes as long as its slowest chain, not the sum of its parts. Work that out before starting, and afterwards state exactly what ran.

This applies to a job of about 15 minutes or more, several checks together, or a rerun of either after a change, from planning it to writing up what ran.

## Say what didn't run

Every check that didn't run, planned or not, and every result reused from an earlier run, gets this block in the same report as the result (the reply, the PR body, the release note):

```
Skipped: <what didn't run>
Safe because: <why>
Caught by: <what would catch a problem>
```

When you can't show it's safe, say so: `Safe because: not shown`, `Caught by: nothing yet`, and name the risk. Never invent a reason to fill the block.

A skip never reads as a pass: never write "all green" over a partial run. This skill drops no gate the repo or the user requires, such as `lane trial` before ready, a review or an install smoke test.

## Plan the run

Answer these in order, in the plan itself.

1. **Where does the time go?** Find each part's last measured time, and whether it waits or burns CPU (its log, the load average, cores and memory free). Parts that mostly wait stack well on one machine.
2. **What can the change reach?** Read the diff, including what a rebase brought in. Run what it can reach, and count anything shared (a lockfile, build config, a common module) as reaching all it feeds. Rerun a baseline on main only where main changed what's measured. Prove each risk with the cheapest test that truly hits it. Guard a computed test list: an empty one can run the whole suite.
3. **What evidence still holds?** A past pass holds only for the same tree hash and the same inputs: dependencies, runtime, environment, services and data. `lane trial` merges other lanes' work, so its tree isn't your tree.
4. **What runs at once?** Cheap checks first, so a broken build fails fast, then every independent long part together, as far as cores and memory allow. If you don't know whether two parts share a port, database, lock or output dir, find out: read the config, or try a small slice on throwaway state. Unknown is a question to answer, not a default to serial. If neither route can settle it, keep those parts apart and say so. Keep parts apart too when they do share state. Timing-sensitive checks go last, on their own, since load can fail them. Split a part further only with cores and memory to spare, and check the gain against a run.
5. **What voids what?** Review before sweeps. The long matrix runs once, at the final head.

Whatever step 2 drops is a skip, so it gets the block above. Past that, cutting a check comes last: try step 4 first, since it gives up no coverage.

Keep a signal that the load changed nothing, beyond the pass itself: a line each part prints, such as how many waits gave up or tests retried, or time per case against the last run.

While a lock or build is busy, prepare the next step without touching the tree under test: script the run, draft the PR text, or work on a separate branch in another worktree.

For CI, ask the same questions: what runs concurrently, what skips by path, what's cached, and what the deploy repeats from the checks.

## Quoting a time

Cite a measured run, or write "unmeasured". A parallel time stays unmeasured until it has run.

## Example

A browser sweep on 12 cores ran its parts one after another: 2 h 37 min for one engine, including a 15-minute wait for a lock, and most of it waiting for pages to settle. Every part at once in both engines, holding that lock once for all of them, took 40 min. The load signal was the count of waits that gave up: 0 of 1,537 in each run. Splitting each part again took 38 min at a load of 60 to 70, so it saved almost nothing. At a load of 45, one timing-sensitive step failed twice, then passed five of five on a quieter machine.

## See also

`delegation` for splitting work across agents. `coding-practices` rules 11 and 12 for verifying claims.
