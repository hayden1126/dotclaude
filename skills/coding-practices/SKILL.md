---
name: coding-practices
description: Hayden's code-quality standards. Use whenever writing, refactoring, or reviewing code in any language. Covers clean-not-just-simple, root-cause fixes, no backward-compat cruft, tests-first, and Python formatting conventions.
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

## Python function pattern
```python
def method_name(self,  # self on the same line; it adds no info, so no separate line
    param1: Type,
    param2: Type,
) -> ReturnType:
    """One-line docstring. No ultra-long docstrings."""
    ...
```
