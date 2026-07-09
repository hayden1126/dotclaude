---
name: staged-reader-review
description: Use when evaluating clarity, coherence, pacing, or scope drift in a multi-section written document (paper, report, RFC, proposal, blog post) before sharing or publishing, especially when whole-document review would smooth over per-section pacing problems, undefined terms, and missing context that fresh readers would trip on. In a sourced project, run it on the rendered output after [formatting mode] completes; it produces the forced artifact <draft>.reader-review.md.
---

# Staged Reader Review

## Overview

Multiple persona-defined blind readers receive the document one section at a time, in lockstep, with no peek ahead. Each writes a reaction and rates clarity and coherence per section in the moment, then synthesizes a final report. The parent consolidates everything into one forced artifact, `<draft>.reader-review.md`. This catches pacing problems, jargon misses, and scope drift that whole-document review smooths over: defects that live in the joint distribution across sections, not in any sentence.

## When to use

- Before a multi-section draft leaves the writer's hands (submission, publication, sharing).
- In a sourced project: after `[formatting mode]` completes, on the rendered output, invoked from `[collaborative mode]`. Recommended for any ship-worthy draft.
- Pacing or scope-drift problems suspected (the writer is too close to the text).
- Multi-audience document where each audience's perspective matters independently.
- Unsure whether non-specialists can follow the technical machinery.

**Don't use when:** very short documents (under 3 sections), pure correctness review, or a draft still being actively rewritten.

The review never self-triggers: the writer asks for it. It does not block `[formatting mode]`; formatting stays the terminal pipeline stage, and the review runs after it.

## Input

Readers judge what a real reader receives, not the source prose.

- In a sourced project, review the rendered sibling with resolved citations: `<draft>.gdocs.md` or `<draft>.plain.md`. For the `word` and `latex` targets the rendered file is a `.docx` binary or `.tex` markup; render a `plain-markdown` sibling first and review that. Never review `<draft>.pandoc.md`: its citations are unresolved `[@id]` tokens no real reader sees, and they distort clarity ratings.
- Outside sourced, any multi-section document works: use the file as it will be shared or published.

Split the document at its natural section boundaries; never split mid-argument. Every section payload must be self-contained (text, tables, and figure captions inline), because readers cannot fetch files.

## The pattern

1. **Pre-flight.** Record the upstream gate artifacts (next section), pick personas, split the document into sections.
2. **Spawn one subagent per persona.** The spawn message carries the persona briefing, the rating protocol, the no-peek-ahead rule, the `END` trigger, and section 1 inline.
3. **For each remaining section:** send it to all readers in parallel, one message per reader. Wait for every response before sending the next section.
4. **After the last section is rated:** send `END` to each reader; each returns a final synthesis.
5. **Consolidate** into `<draft>.reader-review.md` per the artifact schema below.

## Pre-flight: record the upstream gate artifacts

In a sourced project, `[editing mode]` is required to emit four forcing artifacts in the handoff turn that gated formatting, and three per-pass lists in the turns where pass 5 ran. Before reading starts, check the editing transcript and record in the artifact's `## Protocol` section whether each artifact was emitted where required, marked `present` or `absent`:

- revision report (handoff turn)
- §4 audit list (handoff turn)
- citation-payload re-read list (handoff turn)
- voice audit surface-scan report (handoff turn)
- pass-5 proper-noun consistency list (pass-5 turns)
- pass-5 paste-artifact list (pass-5 turns)
- pass-5 punctuation mechanics list (pass-5 turns)

These are transcript emissions, not files on disk: `present` means visible in the editing transcript, in the turn where the artifact is required. An `absent` artifact does not halt the review; the record makes a silently skipped gate visible in a durable artifact instead of leaving it unchecked. Outside a sourced project, mark the pre-flight `not applicable`.

Readers never see this record, the citation log, the brief, the voice file, other readers' output, or any upstream audit report. An upstream self-audit that reported no flags is not evidence; the readers exist to judge independently.

## Reader personas

Default trio for academic drafts:

| Persona | Background | Watches for |
|---|---|---|
| Domain expert | Has used the techniques in own work | Over-claims, misframing, missing mechanism |
| Methods skeptic | Stats / methodology background | Probe protocol, controls, leakage, multiplicity, metric choice |
| Cross-disciplinary reader | Adjacent field, general literacy | Pedagogical clarity, jargon, undefined terms |

Substitute when the document isn't academic. For an RFC: PM, eng lead, on-call engineer. For a blog post: target reader, SME, skeptical commenter.

All personas run on the same base model, so more readers can amplify a shared blind spot rather than cancel it. Diversity has to be real: make personas differ in what they attend to, not just their label. Always keep one outsider to the document's field; specialists smooth over pedagogical problems. Three is the default; go to five only for a genuinely multi-audience document, never more.

## Rating protocol

Per section, in this order:

1. **Reaction first (80–120 words).** What landed, what tripped them, what they expect next. Writing the reaction before the numbers grounds the score in stated reasoning instead of a gut digit.
2. **Clarity (1–5)**, anchored: 1 = lost, couldn't follow; 2 = followed with real effort; 3 = followable, some re-reading; 4 = clear, minor friction; 5 = effortless on first read.
3. **Coherence (1–5)**, anchored: 1 = disconnected from what came before; 2 = weak link to prior sections; 3 = connects but the thread is thin; 4 = builds cleanly with a small gap; 5 = each claim follows from the last.

Hard rules in every briefing:

- **Rate comprehension, not prose quality.** Judge whether the section lands for the reader; explicitly ignore eloquence and polish. Fluent writing that doesn't land scores low; plain writing that lands scores high.
- Don't speculate about future content; rate only what you've read.
- Don't propose rewrites. Be honest, not polite. Use the full scale; a 1 and a 5 are both fair.

On `END`, each reader returns: clarity arc, coherence arc, strongest and weakest section, single highest-leverage change, and a verdict from the fixed vocabulary `accept | minor revision | major revision`.

## Why no independent re-scoring

Letting a reader's accumulated confusion bleed into later sections is deliberate, not a bias to correct. Generic LLM-judge advice says evaluate each section independently so early scores don't taint later ones. That would gut this instrument: a real reader who got lost in section 2 does struggle more in section 5, and surfacing exactly that cascade is the point. Keep readings sequential and stateful. Do not "fix" this into per-section isolated scoring.

## Orchestration mechanics

- One-shot subagents, one per persona. Spawn with a stable name; message each reader to deliver the next section. Address by ID if name lookup fails after the first round trip.
- Send sections to all readers in lockstep and wait for every response before advancing. Sections out of order break the coherence signal.
- Consolidation is parent-owned: convergence judgment stays in one place, never delegated to a reader or a coordinator.

## Consolidating

- Build the ratings table (rows = sections, columns = readers).
- **Concerns raised by 2 or more readers** are almost always real; they become `RR` findings, surfaced prominently. Single-reader concerns become `RN` notes, listed separately (often scope-specific).
- **High rating spread on a section** (readers disagree, e.g. 2 / 5 / 3) is flagged ambiguous or reader-dependent. This is distinct from a section all readers rate low (uniformly weak): the first needs disambiguation for one audience, the second needs a real fix.
- Note the strongest and weakest section per reader (they often differ).
- Top actions: at most 3, keyed to `RR` ids.
- Mark out-of-scope concerns explicitly (need new evidence, contradict the venue, already addressed) so they're deferred, not re-litigated.

Quote verbatim trip points sparingly; compile patterns, not transcripts.

## The artifact: `<draft>.reader-review.md`

The review is a forced artifact: a review that produced no file has not run. It lands as a sibling to the rendered output, keyed to the base draft name, and serves two consumers: the writer now, `[revision mode]` later (its comment-to-change tracking keys off the stable ids).

```markdown
# Reader review: <draft> (<date>)

## Protocol
- Reviewed file: <rendered sibling, e.g. draft.gdocs.md>
- Sections: S1 "<heading>" (<words>w) ... Sn
- Readers: R1 <persona name>: <background, watch-list>. R2 ... R3 ...
- Upstream gate artifacts: revision report <present|absent>; §4 audit list <present|absent>;
  citation-payload re-read list <present|absent>; voice audit surface-scan report <present|absent>;
  pass-5 proper-noun consistency list <present|absent>; pass-5 paste-artifact list <present|absent>;
  pass-5 punctuation mechanics list <present|absent>   <!-- or: not applicable -->

## Ratings
| Section | R1 cl | R1 co | R2 cl | R2 co | R3 cl | R3 co |
|---|---|---|---|---|---|---|

## Findings
### RR-1: <one-line defect> [severity: high|medium|low] [sections: S3-S5] [readers: 2/3]
<verbatim trip-point quotes, compiled reader reasoning, 2-5 sentences>

## Single-reader notes
### RN-1: <note> [reader: R2] [section: S4]

## Verdict
- Per reader: R1 <accept | minor revision | major revision>, R2 ..., R3 ...
- Consolidated: <accept | minor revision | major revision>
- Top actions: <at most 3, keyed to RR ids>

## Out of scope
- <deferred concern, why: needs new evidence / contradicts venue / already addressed>
```

Design points:

- **Stable IDs.** `S<n>` for sections, `RR-<n>` for convergent findings, `RN-<n>` for single-reader notes. Downstream consumers key off these; nothing needs a retrofit later.
- **The verdict vocabulary is fixed to three values** so a future gate can read it mechanically. A draft bad enough to reject is `major revision` plus findings.
- **Quotes are verbatim trip points**, not reader transcripts.
- Markdown, writer-facing. No JSON sibling until a mechanical consumer exists; the schema is regular enough to parse when one does.

## Common mistakes

| Mistake | Fix |
|---|---|
| Whole document at once | Section by section; sectional reactions catch what whole-doc review misses |
| No persona briefing | Generic "review this" gets generic feedback |
| Future sections visible | Readers retroactively justify; you lose real "what next?" expectations |
| Sections out of order | Coherence depends on reading order |
| All-experts trio | Specialists smooth over pedagogical problems; keep one outsider |
| Rating prose, not comprehension | Eloquent-but-doesn't-land must score low; that's the whole signal |
| Reviewing source prose or `.pandoc.md` | Review the rendered sibling; readers judge what a real reader receives |
| Skipping the artifact | A review that produced no file has not run |
| Quoting every reaction | Compile patterns; transcripts overwhelm the writer |
| Acting on every concern | Some need new evidence or contradict the venue; scope-check first |

## Scope and limits

- Read-only over the rendered sibling; the review changes no prose and produces exactly one artifact.
- It never self-triggers and never blocks `[formatting mode]`; the writer invokes it from `[collaborative mode]`.
- It measures reader experience, not authorial voice: a draft can rate 5/5 across sections and still not sound like the writer. Voice fidelity is a separate measure.
- The pre-flight records upstream gate artifacts; it does not enforce them.
