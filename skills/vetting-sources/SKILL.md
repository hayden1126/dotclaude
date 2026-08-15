---
name: vetting-sources
description: Use when an external or third-party document (analyst/broker report, competitor filing, market study, due-diligence pack, research paper) must be brought into a knowledge base and its claims checked before anyone relies on them; when a long PDF must be extracted faithfully with tables, charts, and page-level citations; when auditing whether a document's numbers are accurate, internally consistent, and safe to cite; or when producing a findings or briefing report about an external document. Not for authoring your own slide deck (use deck-production) or for ordinary open-ended web research (use research-discipline).
---

# Vetting sources

## Overview

Turn an external document into vetted, cited knowledge, then a briefing. Three phases: **Extract** it faithfully into an immutable source dir, **Audit** every claim for accuracy and internal consistency, **Brief** the reader on what is safe to use. The whole thing runs as multi-agent workflows so the work is comprehensive and the tool output stays out of the main context.

Two ideas carry it. **Quarantine until it clears**: nothing from the document touches the shared fact registry until the audit passes and the owner approves, because a third-party claim ranks below your primary sources and its forecasts and errors must never leak in. **The scary flag usually clears**: adversarially try to vindicate every discrepancy before trusting it, because the biggest-looking gaps are often correct numbers on a different scope, date, or basis, and the real errors are quieter.

A claim is not knowledge until it is extracted verbatim, traced to a source, and survives an independent skeptic.

## When to use

- A broker/analyst report, competitor filing, or market study needs its numbers checked before they inform a deck, a rebuttal, or a decision.
- A long PDF (filing, prospectus, research paper) must be extracted with tables, charts, and layout preserved and page-anchored for citation.
- Someone asks "is this report accurate?", "what can we quote from this?", or "where does this contradict our filings?".
- You need a findings or briefing report (internal or executive) about an external document.

**Don't use when:** authoring your own deck (`deck-production`), doing open-ended research with no single document to audit (`research-discipline`), or extracting an ebook you own for reading rather than auditing (`ebook-extract`).

## Decisions to lock before you start

Ask the owner, then hold to the answers:

- **Language.** Keep the document's original language verbatim for every claim, number, table cell, and chart label, layering your language on only as section labels and glosses. Never translate a figure before it is audited: translation distorts numbers ahead of the check.
- **Quarantine scope.** Default: write only inside the new source dir until the audit clears. Confirm whether the owner wants any registry integration at all.
- **Forecast depth.** Forecasts cannot be "verified". Decide up front whether the audit checks their internal consistency and reasonableness only, or is asked for more.

## Phase 1: Extract (faithful, multi-agent)

1. **Prep, single-threaded.** First learn the target: where the KB keeps sources, its citation-anchor scheme, and the next source id (e.g. `sources/SRC-NNN-slug/` and `[SRC-NNN:pNN]`). If it has no convention, create one and record it. Then make a new immutable dir for this source and copy the original in. Extract verbatim text (`pdftotext -layout`, or `ebook-extract` / `browser-reader-extract` for owned/DRM files). **Check the text yield: near-empty means the PDF is scanned, so the renders are the only truth (read them visually, or OCR).** Render every page to PNG (`pdftoppm -png -r 200`). Slice text per page. If the document has its own figure/table index, parse it into an exhibit checklist for QA; if not, have each extractor list the exhibits it finds and let QA cross-check page-count completeness instead.
2. **Fan out, one agent per page-batch** (Workflow tool, batches of ~4-5 pages). Each agent reads its page renders AND its text slice, reconciles them (the render is visual truth for tables and charts, the text is the backbone for exact numbers), and writes a per-page block to a disjoint file: section path, verbatim prose, every table as a markdown table, every chart captured as type + axes + series + the plotted values it can read + source line, layout notes, a `[SRC-NNN:pNN]` anchor. See `references/workflow-scaffolds.md`.
3. **Assemble** the disjoint parts centrally into `source.md` with frontmatter that states the reliability tier (third-party, ranks below filings, audit pending). Build a `figures-tables.md` exhibit index.
4. **QA, adversarial completeness.** A second workflow checks the extraction against the renders: every page present, every indexed exhibit captured, table dimensions and totals match, numbers match the image, terms glossed. Fix centrally, re-run until clean. This checks fidelity to the PDF, not real-world accuracy.

## Phase 2: Audit (accuracy + consistency)

1. **Inventory every checkable claim** into a registry row: id, page, category (company-actual, industry, forecast, valuation, qualitative), value, basis-hint (registry / filing / online / internal-only).
2. **Internal-consistency pass** (per section, parallel). Does the arithmetic foot: segment sums to total, growth rate vs level, EPS times shares, valuation multiples. **Reconcile the basis before you flag anything**: apply the stated FX, separate adjusted vs reported profit, and normalize number scales and formats (万/亿 = 10^4/10^8, lakh/crore, decimal-comma). A scale or basis mismatch generates false conflicts faster than anything else. Check units, cross-page contradictions, prose-vs-chart. Report the two disagreeing values and the arithmetic.
3. **External reconciliation** (per claim-cluster, parallel). Company actuals reconcile against your fact registry (cite the canonical fact id). **If the KB has no registry yet (a first import), reconcile company-actuals directly against the company's own primary filings, and seed the registry from the verified subset only at promotion.** The authoritative filing may itself be in the document's language. Industry and qualitative claims reconcile against primary filings and the web. Delegate search method to `research-discipline`. Log every online source with `research-sourcing` (inline its dispatch contract into each web agent; thorough tier when accuracy is the point; spot-check the load-bearing quotes). Give each claim a verdict and a cite-safety mark (below).
4. **Adversarial verification.** Every CONFLICT or MISLEADING finding (the load-bearing ones first if there are many) goes to an independent skeptic prompted to VINDICATE the source: find a legitimate alternative basis (combined vs statutory figure, segment vs whole-market scope, a different as-of date, adjusted vs reported profit, an FX conversion, a number-scale or format difference). A finding stands only if the skeptic cannot justify it. Collapse duplicate findings that share one root cause.
5. **Promote nothing yet.** The brief (Phase 3) is written inside quarantine and is never blocked by it. Quarantine lifts only for PROMOTION, only for the CONFIRMED and verified-new subset, and only after explicit owner sign-off; running autonomously with no owner in the loop, stop at that gate and wait. Promote only genuinely-new, verified data that fills a gap, scope-labeled and ranked below your primary sources. Never promote the document's forecasts or its errors: your registry already holds the truth for anything it also covers.

### Verdict and cite-safety vocabulary

| Verdict | Meaning |
|---|---|
| CONFIRMED | matches a filing or your verified registry |
| CONFLICT | contradicts a filed value (the source is wrong); give the filed value |
| MISLEADING | number is real but framed, scoped, or labeled wrongly |
| UNVERIFIED | no filing and the web was inconclusive (not "wrong") |
| ANALYST-ESTIMATE | a forecast or opinion, not externally checkable |

Cite-safety, for the reader: `safe` (quote as-is), `needs-caveat` (quote with a qualifier), `do-not-cite` (wrong or unsupported). Default crosswalk: CONFIRMED to safe; MISLEADING and UNVERIFIED to needs-caveat; CONFLICT to do-not-cite; ANALYST-ESTIMATE to needs-caveat, or do-not-cite when its inputs are already wrong. Override per claim when context warrants.

## Phase 3: Brief

Order the report so a busy reader gets value top-down: **bottom-line verdict**, then **fix before citing** (ranked, with the correct value and a verifiable source link per item), then **safe to cite** (the confirmed set), then **looks wrong but is fine** (so nobody "corrects" a correct number), then **minor slips**. Write the brief in the reader's language even though the source stayed verbatim through the audit, and re-verify any figure after you translate or reformat it. Delegate prose to `writing-voice`; QA the multi-section draft with `staged-reader-review`.

For an executive PDF: strip every internal reference (file paths, fact ids, method, agent counts). Cite only sources you actually opened and verified; where a correction has no verifiable source, say so rather than invent one. Render a self-contained styled HTML to PDF with headless Chrome (`--headless --print-to-pdf`); see `references/workflow-scaffolds.md`.

## Delegate, do not reimplement

`ebook-extract` / `browser-reader-extract` for raw text with page markers · `dispatching-parallel-agents` for the fan-out · `research-discipline` for how to search · `research-sourcing` for source provenance (inline its contract, never fork it) · `writing-voice` for report prose · `staged-reader-review` for report QA · `deck-production` if the brief becomes a deck.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Translating the document before auditing it | Keep the source language verbatim for every claim until the numbers are checked. |
| Promoting the source's numbers into the registry | They rank below your filings. Promote only new, verified gaps, scope-labeled; never its forecasts or errors. |
| Flagging a discrepancy without an adversarial pass | FX, scope, as-of date, and adjusted-vs-reported explain most "errors". Try to vindicate before you trust the flag. |
| Logging sources at the end or from memory | Log per claim at read time with `research-sourcing`; copy quotes, never recall them. |
| One agent extracting 40 pages | Fan out one agent per page-batch (smaller batches for dense financial-table pages); assemble centrally. |
| Trusting `pdftotext` output on a scanned PDF | Check the text yield; near-empty means image-only, so the renders are the only truth (read visually or OCR). |
| False conflicts from number scale or format | Normalize 万/亿, lakh/crore, and decimal-comma before flagging; a scale mismatch is not an error. |
| Touching shared files before the audit clears | Quarantine holds until the audit passes and the owner approves. |
| Citing an unverified source in the brief to look thorough | Only link sources you opened. No source for a correction? Say so. |
