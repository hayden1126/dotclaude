---
name: deck-production
description: Use when building, revising, or re-targeting a slide deck as code rather than in PowerPoint: investor, board, pitch, or conference decks shipping as PDF, hosted HTML, and .pptx; when every number on a slide must trace to a sourced fact and survive adversarial review; when rebuilding an existing pptx or PDF deck clean; or when translating or re-cutting a built deck for a new audience.
---

# Deck production

## Overview

A storyboard-first, fact-cited, adversarially verified deck, built as a fixed-canvas HTML site and exported to PDF, a self-contained site, and PowerPoint. Slides are one HTML fragment per file, stitched in manifest order; layout comes from a small archetype library; every number carries a citation comment and a public source footer.

Two ideas carry the whole thing. **The storyboard is the spec**, approved by a human before any HTML exists, and amended in the same unit of work whenever a build supersedes it. **Every claim is mechanically traceable**, so a linter rather than a memory catches the slide that quietly changed.

This skill delegates and does not reimplement: `writing-voice` for copy, `dataviz` before any chart, `artifact-design` for visual craft, `chrome-devtools` for the screenshot loop, `handoff` at phase boundaries. It defines no status document.

## When to use

- Building a deck that will be presented externally, where a wrong number is expensive.
- Rebuilding an existing pptx or PDF deck rather than editing it.
- Deriving a translated or re-targeted variant from a deck already built this way.
- Any deck where "which slides changed, and did anything else change with them" must be answerable.

**Don't use when:** a five-slide internal update, a deck someone else will keep editing in PowerPoint, or a single chart that belongs in an artifact.

## Where you are

Three commands orient a resuming session. Run them before reading anything else.

```bash
cat <deck>/deck.toml                     # static config, including rigor tier
head -12 <deck>/storyboard.md            # frontmatter: status, approved_by, approved_on
deckkit lint <deck>                      # what is built, what is broken
```

Those three answers select exactly one row of the phase table. Load that row's reference and nothing else.

## The phase model

Every phase exits the same way: **gate green, fingerprint unchanged or delta documented.** Gate green means the rebuild is deterministic, lint is 0 errors and 0 warnings, and geometry has 0 violations on every touched slide.

| Phase | Produces | Exit gate | Human gate |
|---|---|---|---|
| **0** Ingest *(optional)* | `sources/` with provenance filenames, renders, verbatim text, media, keyframes | substrate lint passes | G0 substrate accepted |
| **A** Frame | facts packs, `storyboard.md`, preflight ledger | every row has an archetype, an act, a hero, and a source line; every cited ID resolves | G1 brief and tier · **G2 storyboard approval (HARD STOP)** |
| **B** Scaffold | deck tree, theme, subset fonts, vendored reveal, css trio, `index.html` with `?export` | `build --allow-draft` and `lint --allow-draft` clean; 3 proof slides screenshot correctly | G3 parallelism consent · G4 theme proof |
| **C** Build | `slides/*.html` in batches, one verifier record per slide | every manifest row reads `reviewed`; lint 0/0; geometry 0; every finding triaged | G5 first-batch taste check |
| **D** Harden | `reviews/hardening.md`, FLAG baseline, contact sheets, media play-test | the nine-point acceptance gate | G6 decision ledger, one batched message |
| **E** Ship | PDF from `?export`, notes-stripped site zip, export record | PDF pages equal slide count; zero notes in the distributable, source retains them | G7 ship artifacts · G8 distribution |
| **F** Variants *(optional)* | pptx pair, translated or re-targeted decks | variant-diff sweep green; glyph coverage green for the new language | G2 re-runs on the diff only |

Phases are resumable. A phase boundary is the clean boundary for `handoff`. Inside C and D the unit of work is the batch, not the phase.

## The two hard gates

**G2, the storyboard gate.** No fragment is written before a human approves the storyboard. On disk that means `status: approved` in `storyboard.md` frontmatter, with `approved_by` and `approved_on`. `deckkit build` exits non-zero without it and `deckkit lint` reports it as an error. `--allow-draft` exists for Phase B infrastructure checks and prints a banner; it is not an approval.

**G3, the parallelism gate.** Parallel slide builders relax a standing rule against parallel edits. It is safe only under one condition: **each builder writes exactly one new file that no other agent touches.** Everything else, including asset copies, storyboard amendments, fixes to reviewed slides, lint, screenshots, and geometry, stays orchestrator-single-threaded. Get explicit consent once per user before the first parallel batch.

## Scaling

Rigor is a field in `deck.toml`, not a judgment. Lint prints the derived value on every run.

```
rigor = regulated   if issuer_listed, or audience is external-investor or
                       regulated-external, or any slide carries a forward
                       financial target
      = sketch      if slides <= 15 and audience is internal and there are no
                       external references
      = standard    otherwise
```

A human may raise the tier freely. Lowering it moves one step and must write `rigor_reason` into the review record. An agent may never lower it.

A `regulated` 50-slide deck runs six preflight lenses, verifies every finding, sweeps every slide at high effort, and passes all nine human gates. A `sketch` 12-slide deck runs one facts agent, no preflight lenses, no sweep, geometry on the slides that use absolute positioning, and three human gates. Same shape, roughly a tenth of the agents.

Batch sizing is mechanical too: write batches never split an act and cap at 18 slides, and **the first batch caps at 4** because it is G5's evidence. Read-only batches are fixed at 10.

## The three governing artifacts

**`storyboard.md`** is the spec: a manifest table (`| # | file | title | archetype | act | status | fact IDs | assets |`) plus a per-slide detail block that mandates exact wording using four move types, `MUST:`, `NEVER:`, `LABEL:`, and `SOURCE:`. A build supersedes the spec only by amending it in the same unit of work.

**The substrate**: a fact registry, `voice.md`, and `sensitive.md`. Default is deck-local files inside the deck directory. If the repo has a `facts/` tree, the scaffolder detects it once and records the answer in `deck.toml`. Nothing re-detects afterward, and a broken path fails loudly rather than validating slides against an empty registry.

**`BUILD-CONTRACT.md`** is the contract every builder agent reads first. The orchestrator never reads it into its own context; agents get the path. That is what keeps a 50-slide build affordable.

## The citation chain

```
registry row  ->  manifest declares the slide's IDs  ->  <!-- F-104 --> inside
the element holding the number  ->  <footer class="src"> naming sources + dates
```

Registry IDs never render. Lint audits the chain in both directions, reports flagged rows loudly, and errors if an ID appears in rendered text. Presenter notes are excluded from "rendered": reveal hides them and the packager strips them.

## Tools

Everything runs through one dispatcher, which also picks the right interpreter (font work needs fontTools in the system python; pptx work needs python-pptx in a venv).

```bash
deckkit                      # the subcommand list, generated from what exists on disk
deckkit <command> --help     # flags for one command
```

**There is deliberately no copy of the CLI surface in this file.** The dispatcher generates its list from the scripts actually present, so it can never advertise a tool that has not been written, and each subcommand's flags come from its own argparse. Read it from the tool, not from here.

The loop you will run most: `deckkit build` then `deckkit lint`, then `deckkit serve` and look at it. `deckkit build --check` writes nothing and diffs, which is the determinism assertion every phase exit needs. `deckkit regress --ref-deck PATH` is the gate to run green before editing any script in this skill.

If `deckkit` is not on your PATH, it is at `~/.claude/skills/deck-production/scripts/deckkit`. `setup.sh` symlinks it into `~/.local/bin` when that directory exists.

## The three failures that cost the most

1. **reveal writes an inline `display: block` on the presented section.** Inline style beats every selector including `#id`, so `display: grid` on a `<section>` is dead CSS on the live slide. A fragment previewed on its own still looks right, which is exactly what hides the bug. All slide layout attaches to a direct child `div.wrap`. Lint enforces both halves, in fragment styles and in shared CSS.
2. **Screenshots do not reveal overlap.** Query real geometry and assert numerically before judging pixels. After a ground-changing fix, re-check the slide and both neighbours, and iterate to convergence: on the one occasion this was skipped, each fix created new overlap and it took four rounds.
3. **Records go stale, including your own.** A prior session recorded a fix that had never been applied; the hardening sweep caught it. Any assertion entering an acceptance gate is re-derived from files in the same session.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Building a fragment before the storyboard is approved | That is G2. `deckkit build` refuses; do not reach for `--allow-draft` to get past it |
| Two agents writing the same file | Builders write one new file each. Everything shared is orchestrator-only |
| Editing `index.html` by hand | It is generated. Edit the fragment and run `deckkit build` |
| `display:` on a section | Attach layout to `> .wrap` |
| Judging a slide from an isolated fragment preview | Judge only through the built deck served under reveal |
| A number with no date, or no unit | Both are forbidden on the face, not discouraged |
| A registry ID in rendered text | Citations are comments; the footer names sources and dates |
| An unqualified superlative | Qualifier and source, or delete it |
| Restating a value that already has a registry row | Cite the ID. One home per fact, or it goes stale |
| Fixing a fragment without amending the storyboard | Mandated wording and ID-set changes are amendments, in the same unit of work |
| Treating verifier findings as instructions | Triage first. Overrides are recorded with a reason |
| Dropping a refuted finding | Keep it, with the refutation, or a later session re-finds it |
| A FLAG baseline delta shipped unexplained | Deltas are fine; silent deltas are the defect |
| Skipping the subsetter after a copy change | New glyphs tofu silently. Lint catches it only if you run it |
| Using a reference render as a pixel target or a number source | It is layout and atmosphere reference only |
| Shipping a review record or presenter notes | The packager copies an allowlist; keep it that way |
| Editing a script without running `deckkit regress` | The gate exists because the reference deck is not migrated |

## Reference material

Detail belongs beside the phase that needs it, in `references/`, loaded one at a time.

**`references/` does not exist yet.** Until it does, the operational detail lives in three places that are current by construction: the phase model above, `BUILD-CONTRACT.md` instantiated inside a scaffolded deck, and `deckkit doctor` for anything environmental. Run `deckkit` to see which tools exist; the phases that depend on the missing ones (geometry gate, PDF, pptx, ingest, theme extraction) cannot be executed yet.
