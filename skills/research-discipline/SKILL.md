---
name: research-discipline
description: How Hayden wants research done before non-trivial implementation. Use when asked to research, find best practices, or evaluate approaches, and before the first edit on any unfamiliar or non-trivial coding task.
---

# Research discipline

Search before implementing. Become an expert on the current best approach before writing code.

## Search for the problem, not the solution
Describe what you need, not the library or version you assume. Stay open to solutions you did not know existed.

- Bad: "tower_governor 0.4 axum rate limiting", "rust seccomp sandbox python subprocess"
- Good: "rate limiting rust best practice 2026", "run untrusted python code safely rust", "sandbox user code execution linux"

If you catch yourself adding a specific library name or version to a query, rewrite it to describe the problem instead.

## Self-correction triggers
- If you are about to implement something non-trivial without searching, stop and write "let me search for best practices first," then search.
- If a page will not load but you genuinely need it, do not guess or hallucinate. Pause and ask Hayden to open a browser and paste the data.

## Use the right source
- Use Context7 (context7 MCP) for version-specific library and framework docs.
- Prefer primary sources and recent material. Note the date when recency matters.
