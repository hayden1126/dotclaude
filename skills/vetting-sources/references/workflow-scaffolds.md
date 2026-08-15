# Workflow scaffolds for vetting-sources

Copy-adapt skeletons for the Workflow tool. Paths and page counts are examples. Keep
code-writing and assembly single-threaded in the orchestrator; agents read and write
only disjoint files.

## Phase 1 prep (deterministic, run before any agent)

```bash
SRC=sources/SRC-NNN-slug
mkdir -p "$SRC/renders" "$SRC/extraction/txt"
cp "$ORIGINAL_PDF" "$SRC/report.pdf"
pdftotext -layout "$SRC/report.pdf" "$SRC/report.layout.txt"   # verbatim text backbone
pdftoppm -png -r 200 "$SRC/report.pdf" "$SRC/renders/p"        # one PNG per page, ~1654x2339
# normalize to p01.png..pNN.png, then split report.layout.txt on form-feed (\f) into extraction/txt/pNN.txt
```

Parse the document's own figure/table index (插图目录 / list of exhibits) into a
`page -> [exhibits]` map. That map is the QA checklist in Phase 1 step 4.

## Phase 1: per-page extractor (one agent per page-batch)

```javascript
export const meta = { name: 'extract', description: '...', phases: [{title:'Extract'}] }
const BASE = '/abs/sources/SRC-NNN-slug'
const BATCHES = [{n:'01',lo:1,hi:4}, /* ... */]
phase('Extract')
await parallel(BATCHES.map(b => () => agent(
  `Extract pages ${b.lo}-${b.hi}. For each page: Read the render ${BASE}/renders/pNN.png
   (visual truth for tables/charts) AND ${BASE}/extraction/txt/pNN.txt (exact prose/numbers).
   Emit a markdown block per page: section path; verbatim prose (source language);
   short gloss in your language; EVERY table as a markdown table (cells verbatim);
   EVERY chart as type + axes/units + series + the plotted values you can read + source line;
   layout notes; a [SRC-NNN:pNN] anchor. Expected exhibits per page: <inject the index map>.
   Write all your pages to ${BASE}/extraction/batch-${b.n}.md, then return the manifest.`,
  { label:`extract:${b.n}`, phase:'Extract', agentType:'general-purpose',
    schema:{type:'object',additionalProperties:false,
      properties:{batch:{type:'string'},pages_done:{type:'array',items:{type:'integer'}},
        low_confidence:{type:'array',items:{type:'string'}},file_written:{type:'string'}},
      required:['batch','pages_done','file_written']} })))
// then concatenate batch-*.md in page order into source.md (orchestrator, deterministic)
```

QA pass: same shape, 2 agents over page halves, each Reads renders + the assembled
blocks and returns `{missing_pages, missing_exhibits, findings[]}`. Fix centrally.

## Phase 2: reconciliation cluster (filing + online)

Slice the claim registry into clusters. Filing-based agents cite your registry ids and
need no web. Online agents get `research-sourcing`'s dispatch contract inlined, plus a
shard path, and use WebSearch/WebFetch (load via ToolSearch).

```javascript
// online cluster agent (thorough sourcing tier)
agent(`Verify these claims against filings AND the web. <cluster rows> <facts registry map>.
  ${RESEARCH_SOURCING_CONTRACT /* inlined verbatim, shard path = research-sources/shards/<id>.json */}
  For each claim write one TSV verdict line (claim_id, verdict, cite_safety, check_basis,
  true_value, note) to ${BASE}/audit/verdicts-<cluster>.tsv. Verdicts:
  CONFIRMED|CONFLICT|MISLEADING|UNVERIFIED|ANALYST-ESTIMATE. cite_safety: safe|needs-caveat|do-not-cite.`,
  { label:`recon:<cluster>`, agentType:'general-purpose', schema:/* counts + conflict ids */ })
```

Internal-only rows (mostly forecasts) can be stamped ANALYST-ESTIMATE deterministically.
After the batch: merge shards, validate, spot-check up to 3 load-bearing quotes against
their `quote_trace`, render `research-sources/SOURCES.md`, delete merged shards (per
`research-sourcing` protocol).

## Phase 2: adversarial verifier (theme-grouped skeptics)

```javascript
// one skeptic per theme; each tries to VINDICATE the source
agent(`Adversarial verifier. Findings <theme rows> claim the source is wrong vs filings.
  Try HARD to find a legitimate basis under which each is correct: combined vs statutory,
  segment vs whole-market scope, different as-of date, adjusted vs reported profit, FX.
  Rule each: upheld (real error) | overturned (false positive) | reclassified (reframe/severity).
  Note where several findings share ONE root cause. Return the rulings object.`,
  { label:`verify:<theme>`, agentType:'general-purpose', schema:/* rulings[] */ })
```

Keep only upheld findings (and reclassified ones, at their new severity) for the brief.

## Phase 3: executive PDF (self-contained, headless Chrome)

Write one self-contained styled HTML (A4 `@page`, inline CSS, tabular-nums, no external
assets). Strip internal references. Then:

```bash
CHROME=~/.cache/puppeteer/chrome/*/chrome-linux*/chrome   # or the installed Chrome path
"$CHROME" --headless --disable-gpu --no-sandbox --no-pdf-header-footer \
  --print-to-pdf="out.pdf" "file://$PWD/report.html"
pdftoppm -png -r 110 out.pdf pg && Read pg-1.png   # eyeball layout, CJK, tables before sending
```

`<a href>` links render clickable in the PDF; use them for the verifiable source per
correction. No em dashes in the prose (see `writing-voice`).
