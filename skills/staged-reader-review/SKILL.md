---
name: staged-reader-review
description: Use when evaluating clarity, coherence, pacing, or scope drift in a multi-section written document (paper, report, RFC, proposal, blog post) before sharing or publishing — especially when whole-document review would smooth over per-section pacing problems, undefined terms, and missing context that fresh readers would actually trip on.
---

# Staged Reader Review

## Overview

Multiple persona-defined readers receive the document one section at a time, in lockstep, with no peek ahead. Each writes a reaction and rates clarity and coherence per section in the moment, then synthesises a final report. Captures pacing problems, jargon misses, and scope drift that whole-document review smooths over.

## When to Use

- Before submitting / publishing a near-final draft
- Pacing or scope-drift problems suspected (the writer is too close to it)
- Multi-audience document; each audience's perspective independently
- Unsure if non-specialists can follow the technical machinery

**Don't use when:** very short docs (< 3 sections), pure correctness review, or a draft you're still actively rewriting.

## The Pattern

1. Pick personas (default trio below); split the document into natural reading units (don't split mid-argument).
2. Spawn one `Agent` per persona. Spawn message = persona briefing + rating protocol + no-peek-ahead rule + `END` trigger + Section 1 inline.
3. For each remaining section: one assistant message with N parallel `SendMessage` calls. Wait for all responses before sending the next.
4. Once the last section is rated, send `END` in parallel → each reader returns a final synthesis. Consolidate into one report.

## Default Reader Trio

| Persona | Background | Watches for |
|---|---|---|
| Domain expert | Has used the techniques in own work | Over-claims, misframing, missing mechanism |
| Methods skeptic | Stats / methodology background | Probe protocol, controls, leakage, multiplicity, metric choice |
| Cross-disciplinary reader | Adjacent field, general literacy | Pedagogical clarity, jargon, undefined terms |

Substitute when the document isn't academic — e.g., for an RFC: PM, eng lead, on-call engineer; for a blog post: target reader, SME, skeptical commenter.

All personas run on the same base model, so "more readers" can amplify a shared blind spot rather than cancel it — diversity has to be real. Make personas differ in *what they attend to*, not just their label. Always keep one outsider; specialists smooth over pedagogical problems. Three is the default; go to five only for a genuinely multi-audience document, never more.

## Rating Protocol

Per section, in this order:

1. **Reaction first (80–120 words).** What landed, what tripped them, what they expect next. Writing the reaction before the numbers grounds the score in stated reasoning instead of a gut digit.
2. **Clarity (1–5)**, anchored: 1 = lost, couldn't follow; 2 = followed with real effort; 3 = followable, some re-reading; 4 = clear, minor friction; 5 = effortless on first read.
3. **Coherence (1–5)**, anchored: 1 = disconnected from what came before; 2 = weak link to prior sections; 3 = connects but the thread is thin; 4 = builds cleanly with a small gap; 5 = each claim follows from the last.

Hard rules in the briefing:
- **Rate comprehension, not prose quality.** Judge whether the section *lands for the reader*; explicitly ignore eloquence and polish. Fluent writing that doesn't land scores low; plain writing that lands scores high.
- Don't speculate about future content; rate only what you've read.
- Don't propose rewrites. Be honest, not polite. Use the full scale — a 1 and a 5 are both fair.

On `END`: clarity arc, coherence arc, strongest/weakest section, single highest-leverage change, overall recommendation (accept / minor / major / reject).

## Orchestration Mechanics

- `Agent` spawn with `name:` (stable handle); `SendMessage` to resume. **Address by ID** if name lookup fails after the first round-trip — the runtime surfaces the ID.
- Section payloads must be self-contained (text + tables + figure captions inline); readers can't fetch files.
- Wait for all background-task notifications before sending the next section.

## Consolidating

- Ratings table (rows = sections, columns = readers).
- **Concerns raised by ≥2 readers** → almost always real; surface prominently. Single-reader concerns → list separately (often scope-specific).
- **High rating spread on a section** (readers disagree, e.g. 2 / 5 / 3) → flag as *ambiguous / reader-dependent*. This is distinct from a section all readers rate low (*uniformly weak*): the first needs disambiguation for one audience, the second needs a real fix.
- Strongest/weakest section per reader (often differs).
- Top three actions the user could actually take.
- Mark out-of-scope concerns explicitly (need new compute, contradict venue, already addressed) so they're deferred not re-litigated.

Quote sparingly; compile patterns, not transcripts.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Whole document at once | Section by section — sectional reactions catch what whole-doc review misses |
| No persona briefing | Generic "review this" → generic feedback |
| Future sections visible | Readers retroactively justify; you lose real "what next?" expectations |
| Sections out of order | Coherence depends on reading order |
| All-experts trio | Specialists smooth over pedagogical problems; keep one outsider |
| Rating prose, not comprehension | Eloquent-but-doesn't-land must score low; that's the whole signal |
| Quoting every reaction | Compile patterns; transcripts overwhelm the user |
| Acting on every concern | Some need new evidence or contradict the venue — scope-check first |

## Why no independent re-scoring

Letting a reader's accumulated confusion bleed into later sections is **deliberate, not a bias to correct**. Generic LLM-judge advice says evaluate each section independently to avoid early scores tainting later ones. That would gut this tool: a real reader who got lost in section 2 *does* struggle more in section 5, and surfacing exactly that cascade is the point. Keep readings sequential and stateful. Do not "fix" this into per-section isolated scoring.

## Real-World Use

Applied to a paper revision: 3 readers × 8 sections. Surfaced an F1↔κ presentation issue all three readers tripped on, methodological concerns (paralog leakage, multiplicity, unquantified uncertainty), and jargon density. 17 in-scope edits applied; 13 deferred for future computation.
