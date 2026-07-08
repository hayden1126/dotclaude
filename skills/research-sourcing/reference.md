# research-sourcing reference

Schema, dispatch contract, and merge/render protocol for the `research-sourcing` skill. This
file is self-contained on purpose: the orchestrator pastes the relevant parts into each subagent
prompt, and subagents run in isolated context and cannot read it themselves.

Two rigor tiers. **lean** uses the core fields only. **thorough** adds the verification fields and
turns on the orchestrator spot-check. The invoker picks the tier; default is lean.

---

## 1. Log entry schema

One entry per source-use. If the same source supports three separate claims, that is three
entries. Fields are the same shape whether the entry sits in a subagent shard or the merged log.

### Core fields (required on every entry, both tiers)

| Field | Meaning |
|---|---|
| `id` | Short stable slug `<source-slug>-NNN`, e.g. `mdn-early-hints-001`. `NNN` is a zero-padded per-source counter from `001`. |
| `claim` | The specific claim in the research output this entry supports. Not the topic, the claim. |
| `title` | Title of the page, document, or source. |
| `source` | Where it came from: a URL, a file path, `user-provided`, or a tool name (e.g. `WebSearch`). |
| `author_or_site` | Byline author, or the publishing site/org, or `none stated`. Do not invent an author. |
| `published` | The source's own publication or last-updated date, or `undated`. |
| `accessed` | Date the agent retrieved it, ISO 8601 (`YYYY-MM-DD`). |
| `location` | Anchor inside the source: section heading, paragraph, timestamp, page, or URL `#fragment`. |
| `exact_quote` | A single contiguous span copied **verbatim** from the source that supports the claim. Never a paraphrase, never stitched across passages, never reconstructed from memory. |

### Thorough-tier fields (also required when tier is `thorough`)

| Field | Meaning |
|---|---|
| `access_mode` | One of `full-page`, `pdf`, `api-response`, `snippet`, `user-provided`. `snippet` = a search-result excerpt or keyword window, not the full source. |
| `verification_status` | `verified` (you read the full context at `location`) or `partial` (snippet or second-hand). A `snippet` access_mode can **never** be `verified`. |
| `quote_trace` | `{ "first_20": "...", "last_20": "..." }`: the first and last 20 characters of `exact_quote` exactly as they appeared in the source. This is the artifact the orchestrator spot-checks. |
| `reliability` | `{ "source_type": "...", "basis": "..." }`. `source_type` is a short label (`official-docs`, `standards-body`, `primary-source`, `peer-reviewed`, `reputable-news`, `vendor-blog`, `forum-answer`, `wiki`, `preprint`, `personal-blog`). `basis` names one checkable reason it is trustworthy for this claim. Generic vouching ("reputable site") does not count. |
| `context` | 1-2 sentences around the quote as printed, or a short note on what the source argues and why it supports the claim. |

### Exemplar entry (thorough tier, illustrative)

```json
{
  "id": "mdn-early-hints-001",
  "claim": "HTTP 103 lets a server send preload hints before the final response is ready",
  "title": "103 Early Hints - HTTP | MDN",
  "source": "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/103",
  "author_or_site": "MDN Web Docs",
  "published": "2024-07-25",
  "accessed": "2026-07-08",
  "location": "Section: Status",
  "exact_quote": "The HTTP 103 Early Hints informational response may be sent by a server while it is still preparing a response, with hints about the resources that the server expects the final response will link.",
  "access_mode": "full-page",
  "verification_status": "verified",
  "quote_trace": { "first_20": "The HTTP 103 Early ", "last_20": "response will link." },
  "reliability": { "source_type": "official-docs", "basis": "MDN Web Docs, maintained reference for web platform features" },
  "context": "MDN's definition of the 103 status, describing it as an informational response carrying resource hints ahead of the final response."
}
```

---

## 2. Dispatch contract (paste into every subagent prompt)

The orchestrator drops this block, verbatim, into each research subagent's prompt, filling
`<tier>` and `<shard-path>`. This is what makes subagents log even though they never load the
skill. For the `thorough` tier keep the bracketed `[thorough]` lines; for `lean`, delete them.

```
=== SOURCE-LOGGING CONTRACT (research-sourcing, <tier> tier) ===
You are logging your sources. As you research, record every source you ACTUALLY use to
support a claim. Collect entries in memory; at the VERY END, write them as a single JSON
array in ONE write to:

    <shard-path>

Do not write anywhere else, do not append incrementally, do not touch any merged log. If you
crash before the final write, that is fine: a missing shard is recoverable, a half-written one
is not.

Each entry is one source-use. Fields:
  Required: id, claim, title, source, author_or_site, published, accessed, location, exact_quote
  [thorough] also required: access_mode, verification_status, quote_trace, reliability, context

Rules:
- exact_quote is a single contiguous span copied VERBATIM from the source. Never paraphrase,
  never stitch across passages, never reconstruct from memory. Cannot copy it? You did not
  verify it: reject the source, do not log it.
- source = the URL / file path / `user-provided` / tool name you got it from.
- published = the source's own date (or `undated`); accessed = today's date (YYYY-MM-DD).
- id = `<source-slug>-NNN`, per-source counter from 001.
- [thorough] access_mode is one of {full-page, pdf, api-response, snippet, user-provided}. A
  `snippet` can NEVER be `verified` - it shows a match, not the source.
- [thorough] verification_status is `verified` (you read the full context at `location`) or
  `partial`. quote_trace = {first_20, last_20} of exact_quote, copied exactly.

REJECT (do not log) when: you could not open the full source, the quote would be a paraphrase,
or you are not sure the source supports the claim. A rejected source is a gap, not an entry.

In your final message, in ADDITION to your findings, return:
  ### Logged   - id + one-line source for each entry you wrote
  ### Rejected - source + why (paywall, snippet-only, off-claim)
  ### Gaps     - claims you could not source
  ### Queries  - the search queries you actually ran
=== END CONTRACT ===
```

If a subagent runs inside the Workflow tool, it may instead return its entries as structured
output (a JSON array matching the schema) rather than writing a shard file; the orchestrator
collects and merges those identically. File shards are the default and work with both the Agent
tool and the Workflow tool.

---

## 3. Merge and render protocol (orchestrator)

Run this only after every subagent in the batch has returned.

**Layout.** Shards at `research-sources/shards/<agent-id>.json`; merged log at
`research-sources/sources.json`; rendered output at `research-sources/SOURCES.md`. The
`research-sources/` root defaults to beside the research output and is overridable at invocation.

**Merge.**
1. Read every shard in `research-sources/shards/` in sorted filename order. A shard that is not
   valid JSON is a failed shard: surface it, do not repair it.
2. Validate each entry. Lean: all core fields present and non-empty, and `exact_quote` is not
   empty, a placeholder, or a restatement of `claim` (that is a paraphrase, not a quote).
   Thorough: additionally require `access_mode`, `verification_status`, and `quote_trace` on
   `verified` entries, and hard-fail any entry that is both `access_mode: snippet` and
   `verification_status: verified`. Surface failing entries with the rule that fired; do not merge
   them.
3. Resolve `id` collisions against the merged log and shards already merged this pass by
   incrementing `NNN`. Lowest shard filename owns its ids, so a rerun is deterministic.
4. Dedup: collapse entries with identical (`source`, `exact_quote`, `claim`). Same source and
   quote supporting a different claim stays a separate entry.
5. Append survivors to `sources.json` (create `[]` first if it does not exist).
6. **Spot-check (thorough only).** Pick up to `ceil(n/4)` merged entries, capped at 3, preferring
   load-bearing claims and `pdf` / `api-response` sources. Re-open each `source`, locate
   `exact_quote`, and confirm its real first-20 / last-20 characters match `quote_trace`. On any
   mismatch, mark the entry `spot-check-failed`, unmerge it, and **escalate**: spot-check every
   remaining entry from the same subagent, since fabrication clusters within one bad session.
   Record spot-check outcomes in the merge summary to the user.
7. Render `SOURCES.md` (below).
8. Delete each successfully merged shard. Rename a failed or abandoned shard to
   `<agent-id>.failed.<timestamp>.json` and keep it.

**Render `SOURCES.md`.** A numbered, per-source reference list. Group multiple quotes from one
source under that source. Optionally append a "Claims index" mapping each claim to its entry
numbers so a reader can trace any claim in the final answer back to a source.

```
# Sources

1. **103 Early Hints - HTTP | MDN** - MDN Web Docs
   https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/103
   Published 2024-07-25 · Accessed 2026-07-08 · Section: Status
   > The HTTP 103 Early Hints informational response may be sent by a server while it is
   > still preparing a response...
   Supports: HTTP 103 lets a server send preload hints before the final response is ready
```
