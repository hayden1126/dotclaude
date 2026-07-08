---
name: research-sourcing
description: Use when the user explicitly asks to log, track, or cite the sources behind a deep-research answer (phrasings like "log your sources", "track provenance", "cite this research", "keep a source log"), especially while an orchestrator is dispatching multiple research subagents whose URLs, quotes, and dates would otherwise be lost. Manual: do not fire on ordinary research unless sourcing is requested.
---

# Research sourcing

## Overview

"I verified this" must produce a copyable artifact, not a mental checkmark. In a multiagent
research run, each subagent logs every source it used (URL, date, exact verbatim quote, the claim
it supports) into a shard; the orchestrator merges the shards, spot-checks them, and renders a
Sources list that lets a reader trace any claim in the final answer back to where it came from.

This skill is advisory and orchestrator-driven. Subagents do not auto-load it, so the orchestrator
must inline the dispatch contract from `reference.md` into every research subagent's prompt. That
inlining is the whole binding mechanism: without it, subagents research with no logging discipline.

## When to use

- The user explicitly asks to log, track, or cite the sources behind a research answer.
- You are dispatching (or about to dispatch) multiple research subagents and want every claim
  traceable to a source.

**Don't use when:** a casual single-source lookup, no multiagent dispatch, or the user has not
asked for sourcing. This is manual. Do not turn it on by default.

## The two tiers

| Tier | Adds | Orchestrator does |
|---|---|---|
| `lean` (default) | core fields only: id, claim, title, source, author_or_site, published, accessed, location, exact_quote | merge, dedup, render |
| `thorough` | core + access_mode, verification_status, quote_trace, reliability, context | also runs the spot-check |

The invoker picks: "log sources (thorough)", or accept the lean default. Full field definitions
live in `reference.md` section 1.

## Orchestrator protocol

1. Set up `research-sources/` (a `shards/` dir and `sources.json`) beside the research output, or
   at the path the user named.
2. Paste the dispatch contract (`reference.md` section 2) into **every** research subagent prompt,
   filled with its `<agent-id>`, `<tier>`, and `<shard-path>`. Never dispatch a research subagent
   without it.
3. Each subagent researches, writes its shard as one JSON array in a single final write, and
   returns its Logged / Rejected / Gaps / Queries report.
4. Merge and validate per `reference.md` section 3: sorted read, field and enum checks, id-collision
   renumber, dedup, append to `sources.json`.
5. Thorough only: spot-check up to `ceil(n/4)` entries (cap 3) against their `quote_trace`; on a
   mismatch, unmerge that entry and escalate to the rest of that subagent's entries.
6. Render `SOURCES.md`, delete merged shards, and report merge and spot-check outcomes to the user.

For how to search well before you log, use the `research-discipline` skill. This skill governs
recording what you used, not how you find it.

## Anti-fabrication rules

Violating the letter of these is violating the spirit: an entry exists to let someone else check
the claim.

- **Quotes are copied, never recalled.** `exact_quote` is a contiguous verbatim span from the open
  source. If you cannot copy it, you did not verify it: reject the source.
- **A search snippet is not the source.** It can never be `verified`. Open the full source or log
  `partial`.
- **Log at read time, per claim.** Not a bundled URL list at the end. Each claim maps to the source
  that supports it.
- **Reject on uncertainty.** A source you are unsure supports the claim is a gap, not an entry.
- **The source you read is the source you log.** Reading a page that cites the target is not reading
  the target.

| Excuse | Reality |
|---|---|
| "I listed the URLs at the end." | A bundle does not say which claim each supports, or whether the quote is real. Log per claim. |
| "I paraphrased it accurately." | A paraphrase you cannot trace to a span is indistinguishable from a reconstruction. Copy the span. |
| "The snippet was clear enough." | A snippet shows a match, not the source. Not `verified`. |
| "I read it a step ago, I recall the gist." | Memory is where fabrication enters. Re-open, or mark `partial`. |
| "That figure is well known (~93%)." | Precise numbers are exactly what gets confabulated. Quote the source or drop the number. |
| "I'll add citations after I draft." | Cite-after reverse-justifies a claim already written. Log when you read. |

## Red flags, STOP

- About to write a specific number, date, or name with no source open in front of you.
- Writing "according to the docs" with no URL and no quote.
- Typing a quote from memory instead of copying it.
- Marking `verified` on something seen only as a search result.
- Saving sources as one list at the end instead of per claim.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Dispatching a subagent without the contract | Inline `reference.md` section 2 into every research subagent prompt; that is the binding mechanism |
| Subagent writes to `sources.json` directly | Subagents write only their own shard; the orchestrator owns the merge |
| Incremental shard writes | Collect in memory, write the whole shard in one final write |
| Skipping the spot-check in thorough mode | The `quote_trace` is only worth logging if something re-checks it; run it and escalate on a miss |
| Turning it on every research turn | Manual only; fire on explicit request |
