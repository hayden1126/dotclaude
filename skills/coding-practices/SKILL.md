---
name: coding-practices
description: Hayden's code-quality standards. Use whenever writing, refactoring, or reviewing code in any language. Covers clean-not-just-simple, root-cause fixes, reproducing bugs first, pinning behavior before a refactor, verified claims, known-limit comments, no backward-compat cruft, tests-first, and Python formatting conventions.
---

# Coding practices

Write code that is clean, not just simple. No development-only hacks. No temporary workarounds. No "for now" approaches. This is production work: quality over speed.

If you catch yourself thinking "for development, the simplest approach is...", stop and find the cleanest production solution instead, or discuss the tradeoff.

## Rules
1. **Imports at top only.** Never mid-function.
2. **No backward-compatibility cruft.** Remove dead code completely. No "kept for compat" remnants.
3. **Clean and minimal.** No legacy leftovers.
4. **DRY.** If two functions can merge, merge them. Check the codebase before duplicating.
5. **Minimal, root-cause fixes.** Fix the cause, not the symptom. Prefer a one-line fix at the source over a five-line downstream workaround. Do not over-engineer the fix.
6. **Tests before implementation** for non-trivial changes. Never delete or weaken existing tests without explicit approval. If there is no test infrastructure, propose one (framework, one example test, layout) and get approval before implementing.
7. **Match the surrounding code.** Naming, comment density, and idioms should look like the file you are editing.
8. **Durations on a monotonic clock.** Deadlines, timeouts and elapsed times read `time.monotonic()` (or the language's equivalent), since the wall clock steps. Keep wall-clock stamps for values shown or compared across processes, and wait on a monotonic deadline derived beside one.
9. **Reproduce a bug first.** For a non-trivial bug, commit the failing repro before the fix. "Might help" is a hypothesis and doesn't ship: test it, and take out what the evidence refutes.
10. **Pin behavior before a refactor.** Write a characterization test that passes on the old code, then refactor with it green.
11. **Verify claims by experiment.** State a claim that can fail, run the same command on the baseline and on the change, and report VERIFIED, NOT VERIFIED or INCONCLUSIVE. Keep scratch output in the temp dir.
12. **Prove a change on the real path.** Exercise what a user would, rather than test-only endpoints, check side effects such as files written or rows inserted, and keep the evidence through cleanup.
13. **Cut slop.** Remove defensive checks abnormal for a trusted path, casts that dodge the type system, and nesting an early return fixes. Validation at trust boundaries stays.
14. **Name known limits.** Finished code with a known limit carries one comment naming it and when to upgrade: `# limit: one writer per lane; needs a lock if lanes ever share a worktree`. The code must be correct for today's real use, or the "for now" ban applies. The comment never exempts code from review.

## Python function pattern
```python
def method_name(self,  # self on the same line; it adds no info, so no separate line
    param1: Type,
    param2: Type,
) -> ReturnType:
    """One-line docstring. No ultra-long docstrings."""
    ...
```
