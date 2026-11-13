# 07 Cheat sheet

Baseline as of 2026-11-12; changes only via `12-retro`.

The sheet the student may bring into the exam: one HTML document printed to PDF, built only when
the exam rules allow it (FB-130). It condenses the verified notes, organized by task, the way the
student will reach for it mid-question (FB-141). When PLAN.md includes a mock (`08-practice`),
this stage builds the mock sheet, `cheatsheet/<exam-slug>-mock.html`: it holds nothing derived
from the mock and is the one published. The final sheet adds the mock-derived items after the
attempt ("The final sheet" below, which 08 runs). Without a mock there is one sheet,
`cheatsheet/<exam-slug>.html` (FB-133). With no sheet allowed, this stage tags the notes page's
Review view instead ("Tag the review" below).

## Step 1: Check the inputs

- CLAUDE.md's rules allow a sheet. Quote the rule in STATUS: its size, one side or two, whether it
  is collected and whether it must carry a name (FB-130). Not allowed: when PLAN.md's `Review
  view:` line gives minutes (intake offered it, FB-143), tag the review instead, as "Tag the review"
  below says, in place of steps 2 to 6. Otherwise skip this stage and log it (as the build's last
  stage, or run alone, removing the `Build running` line).
- `05-verify` is done. The sheet derives from the notes and the checker's output
  (`_build/verify/examples.out.md`) only: never from a key, the mock, or a source MANIFEST marks
  `reserved`, and never an answer from a set it doesn't mark `yes, attempted`.
- The profile (`~/scratch/exam-prep/profile.md`) holds the font floor, color or grayscale, the
  engine, and the "Never print" forms of the name and id (`00-intake`, question 5, FB-131). Any missing: the defaults, a 6 pt floor, colors that
  read in grayscale, HTML built here and printed by Chromium, logged in STATUS. When the engine is
  the student's own LaTeX, they write the sheet and this stage checks it: step 2's gap scans,
  then `check_pdf.py --no-layout`, the page images (an Overfull line in LaTeX's log is an
  overflow), and step 5's audit.
- No notes patch is open (`09-tutor` step 5, "One open patch", in `_build/logs/tutor.md`), since
  this stage writes the sheet and fixes the notes in place. With one open, take out the `Build
  running` line, log in STATUS that this stage waits for the patch and stop: a tutor tab finishes
  it, and the student starts this stage again. Run alone (STATUS has no `Build running` line,
  SKILL.md hard rule 1), add the line now, then check again: a patch dispatched in between takes the
  line out and stops this stage the same way.

## Step 2: Find what goes on it

1. Outline the blocks in `_build/sheet-outline.md`, by task, not by lecture: what the student
   does in a question (trace this, compute that, justify a label, prove), each block under its
   topic (FB-141), one line per item. Split them across the sides.
2. Scan for gaps twice, in order (FB-136). Load the delegation skill first, and spawn from
   `<skill>/templates/agent-briefs.md`, section "Sheet gap scan", unnamed, its `{{Q-ONLY FILES}}`
   slot filled with each question set's copy under `_build/q-only/` (`02-extract` step 3.4, FB-056) and
   its `{{EXTRACT FILES}}` slot with the extracts of the sets that have no copy:
   - by content: the content variant, one agent per two or three notes sections, all at once.
     Pick from their reports (step 3) into the outline;
   - then by question type: one agent, the question-type variant (answer templates, pros and
     cons, a worked pattern per type), over the outline as it now stands, so it adds to the first
     pass's picks instead of repeating them. Pick again.
3. Picking: nothing a MANIFEST.md topic cut takes out (what its backbone Conventions line says stays
   is in), and nothing under a `Not on <exam>` banner, goes on a sheet. Every item must help cold.
   It states its purpose first, and a number says what it is for (FB-135). Nothing points into the
   notes: the student can't open them (FB-134). When the exam asks for proofs, a proof-techniques
   block goes in (FB-079). Log each suggestion you reject, and why, in `_build/logs/sheet-gaps.md`.
4. The figure pass (FB-145), over the outline as picked: for each block, would a drawn figure settle what
   its text leaves the student to work out cold: a direction (which way an arrow, a shift or an
   update goes), a shape (a curve, a tree, a region), which cells or entries a formula uses? List
   each such block in the outline with the figure it gets, drawn from the notes' figures or the
   checker's output, never a new value of your own. When the figure says all its text said, the
   figure replaces the block and the text goes: the sheet never carries both.

## Step 3: Write it

Copy `<skill>/templates/cheatsheet.html` to the sheet's path, fill its slots (`{{FLOOR}}` from
the profile, `{{BODY}}` starting 0.4 pt above it, `{{ID LABEL}}` as the exam's form names the
student id) and drop its opening comment. For A4 paper, follow that comment; for a one-sided
sheet, delete side 2's `.page`. Write the blocks in these classes only (FB-139):

| Class | Use |
|---|---|
| `.page`, `.strip` | one printed side; its header band, title left, side label right |
| `.fill`, `i`, `i.sh` | side 1's write-in box: never the name or id itself (FB-132) |
| `.hue1` to `.hue6` | a topic's color, on the wrapper `div` around its blocks or on a `.span` |
| `h2`, `h2 i` | a topic band; its source tag (`L2`, `HW1`) on the right |
| `.blk`, `.keep` | a block that may break across columns; one that may not |
| `p.k` | a run-in subheading |
| `.hd` | a lead-in label: `Pick` for a decision line, `Trace`, `Justify` |
| `.tr` | a trap, the only red text |
| `.p`, `.m` | a pro and a con |
| `.u` | underline |
| `pre` | pseudocode or a template to copy |
| `table.c`, `.prop`, `.fx`, `.alt` | centered cells; a comparison table; fixed layout; tinted odd rows |
| `.span`, `.foot` | a full-width row at a side's top: a table and its footnote beside it |
| `figure.sf`, `.nd`, `.ed`, `.nl`, `.v`, `.w` | a figure: an inline SVG and its node, edge, node-label, value and weight classes |

- Values come from `examples.out.md` or the notes, never from your own arithmetic (hard rule 3).
- End the last side with a symbol legend for every symbol and abbreviation the sheet uses
  (FB-139).
- SVG text prints at its size times the figure's scale (its width over the viewBox's): keep that
  above the floor (FB-142). `check_pdf.py` measures it. Every axis on every figure carries its
  label (what it measures, and its unit or direction), however obvious it looked when drawn (FB-145).
- The index (FB-144): side 1 ends with a small `.keep` block, `Index`, at the foot of its last column (the
  sheet's bottom right corner), one line per topic block: its name as its band shows it, then its
  side and column (`Sums 1B`, `Walks 2A`), in the order the student would look them up. It is the
  sheet's own map (FB-141): the student finds a block from the sheet in hand, so the cram order
  carries no map of the sheet. Write it once step 4's fill has settled, and correct it after every
  block moved between columns or sides; step 4.3's page images check each line against where the
  block printed.
- Name and id: never printed (FB-132). When the rules say the sheet is collected with a name,
  tell the student in this stage's report, and `08-practice` puts it on the exam-morning card,
  the cram order's `## Tonight` (its step 7).

## Step 4: Print and check

From the hub root, once per sheet:

1. `node <skill>/scripts/print_sheet.mjs cheatsheet/<name>.html cheatsheet/<name>.pdf` writes the
   PDF and `cheatsheet/<name>.layout.json`. It finds Playwright as `06-site` step 5 says.
2. `python3 -I <skill>/scripts/check_pdf.py cheatsheet/<name>.pdf --floor <pt> --forbid "<form>"`,
   one `--forbid` for each entry of the profile's "Never print" line: the forms of the student's
   full name and their id (FB-132). With no such line, use `git config user.name`, don't save it
   to the profile, and flag in STATUS that the check had only that. Add `--paper a4` for A4 and
   `--pages 1` for a one-sided sheet. A `--forbid` hit counts its matches and shows the words
   around each with every form masked (`[#2]'s theorem`). Drop that form for this sheet only when
   every match is an ordinary word and not the name, and log the drop in STATUS by its
   number and page alone: never the form or a masked line, since STATUS is committed. Otherwise
   the name is on the sheet: take it off. It fails on the page count or size, an unembedded font, text below the floor
   or within 13 pt of an edge, a section sign, a `--forbid` text in the PDF or the sheet's HTML, a
   side that clips a spilled column or holds a box wider than its column (FB-138, L60), a remote
   request, and a layout file from another print or a sheet changed since. It warns on the word
   "notes" and on a side with room left. Compare its font list with the sheet's faces: a missing
   face falls back to a wider one (L63).
3. `pdftoppm -r 100 -png cheatsheet/<name>.pdf _build/shots/sheet-<name>` and look at both pages:
   an orphaned heading, a gap under a table, a cramped table, a figure that lost its labels, an
   axis with none, and an index line naming a side or column its block didn't print in.
4. Fill, aiming for each side's content to end in its last column, 0.84 to 0.96 of the way down.
   `--fs` sets both sides at once, so: lower it while any side clips; then move blocks from the
   fuller side to the emptier one; raise it, in steps of 0.1 to 0.3 pt, only while every side
   has room. At the floor, cut wording instead: the floor is a floor, not the body size
   (FB-131). Rerun 1 to 3 after every change.

## Step 5: Audit

A fresh reviewer audits the sheet against the notes, from the Review brief's "Audit" variant
(`05-verify` step 4), with the sheet as the condensation. Apply the findings as `05-verify` step 5
says: check each claim first, and fix every copy of a fact. Then step 4 again.

## Step 6: Ship

- The prune list (FB-146), last: `_build/logs/sheet-prune.md`, one line per block, its name, side and
  column, and the question type it serves (trace, compute, justify, a true or false, as the How
  it's tested table names them), or `none found` when no question type uses it. The student cuts
  the blocks they would not use: run alone with them present, ask now; in the build, which asks
  nothing (hard rule 1), add `Sheet prune: waiting for the student (_build/logs/sheet-prune.md)` to
  STATUS, and `08-practice` step 8's opening asks it. A cut is a change to a shipped sheet ("After
  shipping"), the index corrected with it, and the room it frees goes first to the final sheet's
  items. Log the answer, the blocks cut or `none cut`, and take the STATUS line out.
- Publish the mock sheet (or the only sheet) privately with the Artifact tool, as `06-site` step
  6 does, and put its URL in STATUS. A LaTeX sheet isn't published: the student has it.
- Give the print settings in the report: color or grayscale as the profile says, 100% scale with
  fit-to-page off, and for two sides, double-sided, flipped on the short edge.
- Commit the sheet's source (the HTML, or the student's LaTeX), its PDF and, for HTML, its layout
  file, run alone or as the build's last stage with the `Build running` line removed in that same
  commit (hard rule 1), and hand off. A tutor tab dispatches the patches the student approved
  meanwhile.

## The final sheet (after the mock attempt)

`08-practice` runs this once the student has taken the mock. The mock sheet held no room back
when it was built: it fills like any sheet. So the final sheet makes room for its items. With every
untaken mock declined (`08-practice` step 8, "A mock declined", STATUS's `Mocks declined:` line, FB-195),
the mock sheet is the exam sheet, and this section runs only once the student, told which untaken
mock parts the held items would spoil, says to add them.

1. Copy `<exam-slug>-mock.html` (or the student's `.tex`) to `<exam-slug>-final.html` (or
   `.tex`). A later mock's misses start from the final sheet already built, never a new copy.
2. Add the mock-derived items (the student's misses, and the cold solver's conventions and the
   final-sheet items `08-practice` logged in STATUS for the mocks taken so far or for no mock),
   each verified like any other item. Room comes first from space a scope cut freed and left
   blank (below), then from lowering `--fs` toward the floor, then from replacing items the
   attempt showed the student doesn't need. Near a full page, new wording is no longer than what
   it replaces (FB-137).
3. Steps 4 and 5 for it, the audit limited to what changed, the index corrected for every block
   moved. `diff` the two sheets: it shows the
   added items, what they replaced, the `--fs` line if it moved, any block moved between sides
   and wording cut at the floor, and nothing else.
4. Print it; it isn't published.

## After shipping

- Any change to a shipped sheet, a fix or an addition, runs `08-practice`'s
  "Changing the notes or a sheet", the one list of the published products and what a change does
  to each: the draft shown first (FB-137), every copy of the fact changed, the rebuild and its
  checks, the republish. During study Q&A a dispatched writer makes it (hard rule 9; `09-tutor`
  step 5). For a sheet, that list's rebuild is step 5's audit limited to the change, then step 4.
  A fix to a fact goes into both sheets; an addition the mock prompted goes into the final sheet
  only (FB-133).
- Space a later scope cut frees stays blank for the final sheet's items. Check which sections it
  would help, list them in STATUS, and ask the student when they are next here (FB-140).

## Tag the review (no sheet allowed)

When the exam allows no sheet, the student still needs a recall layer shorter than the notes
(FB-143). It is the notes page's Review view (`_build/CHASSIS.md`): a Review / Full notes toggle
whose Review view shows each section's Must-know list, each subsection's concise box (S34,
untagged: every one shows), the exam-day map and the blocks the notes tag `.rv`, and hides the
rest. It copies nothing: this stage only tags worked examples and pitfalls
the verified notes already hold. Its budget is PLAN.md's `- Review view: <N> minutes of reading`
line, asked at intake, and changed only when nothing is left to untag (below). `assemble.py` counts
the view's words at 150 a minute (`READING_RATE`, an unmeasured estimate for dense study notes) and
fails the build when they take more than N minutes, printing both numbers. The map's cram block (`08-practice` step 7) is left out of the
count: it is a reading list into the notes, not review text. Any later rebuild can still fail on
the minutes (a patch that lengthens a tagged block, a new Must-know line); the remedy is item 4's:
untag from the last ranked subsection up, before anything else. Once no `.rv` tag is left (the
Must-know lists, the concise boxes, the headings and the map count untagged, and no untagging
removes them), untagging can't help: PLAN.md's `Review view:` line gets new minutes, logged in
STATUS. That holds too when the untagged content alone, the boxes above all, already takes more
than the minutes before item 2 tags anything: nothing is tagged, and the minutes are measured
(`assemble.py` prints them) and set as below. This is the one rule for who sets them, and every
other site points here. When the student can't be asked, the session sets the minutes the view now
takes, rounded up, and logs that in STATUS as a judgment call for the student to confirm or change.
The student can't be asked during an unattended build (hard rule 1: a build stage, either
`11-next-exam` source path among them), nor in a `10-polish` pass while a mock is untaken. In a pass
or a source path while a mock is untaken, the student looks away, so the confirm is logged `held for
the look-back` and asked there (as `10-polish` step 6 holds a question). In the build, the
STATUS line reads `Review view: set to <N> minutes (measured), for the student to confirm`, and
`08-practice` step 8's opening asks it, beside its other opening offers (the student is present at
the cram night, and the minutes give away no answer). The student keeps the minutes or sets new
ones (fewer than the measured count can't hold the view's untagged content, which they hear
first); new ones go on PLAN.md's `Review view:` line and the view is rebuilt from item 2 here
(more minutes tag more) through item 5. Either way, the STATUS line comes out once they answer. Otherwise (a pass once every mock is taken, a `09-tutor` patch's merge, `08-practice` step 8.4) the main session asks the student.

1. **Rank the subsections.** Before the cram order exists, by the backbone's How it's tested
   weights; once it exists (`08-practice` step 7), in its rows' order. A subsection under a `Not on
   <exam>` banner, or one a MANIFEST.md topic cut takes out, has no rank.
2. **Tag**, in that order, in the Markdown: per subsection one worked example, `> **Worked example
   N.K: title** {#ex-N-slug .rv}`, and the pitfall that goes with it, `> **Pitfall:** {.rv} ...`
   (`_build/CONVERT.md`'s `.rv`), until the budget is spent. Only a block directly inside its
   section takes the tag, never one inside a list, another callout, a `Not on <exam>` banner or an
   `Unverified` callout, nor any block of a section whose banner comes before its first `##`
   subsection (its first `h3` on the page: cut or unverified whole, so the view leaves it out,
   Must-know list and all): `assemble.py` refuses
   each. Must-know lists and concise boxes are otherwise always in the view, untagged, and count toward
   the budget before any tag does. No text is added: a subsection with no worked example or pitfall shows only through
   its Must-know line.
3. **The fragments.** Make the same edit in each `_build/frag/sec<N>.html`, class `rv` on the
   block as CONVERT.md maps it (or have the section converted again, `06-site` step 3), then
   `06-site` step 3's `fidelity.py`, which compares the marker like an id.
4. **Assemble and check**, `06-site` step 5, all of it. `assemble.py` enforces the budget: over
   it, untag from the last ranked subsection up and rerun from item 3; once no `.rv` tag is left,
   new minutes on PLAN.md's `Review view:` line, asked or set and logged as this section's opening
   says, and rerun. `verify_page.mjs` checks and
   shoots both views; look at the `-review` screenshots too. Since no text changes, `05-verify`
   step 5's questions check needs no extra pages (FB-191), and there is no audit of copied text.
5. **Republish** the notes page to its same URL, as `06-site` step 6 says, its version bumped on
   its STATUS line as `08-practice`'s "Changing the notes or a sheet" item 5 does. Then commit and
   hand off as step 6 does for a sheet (the `Build running` line removed in that commit when this
   stage ends the build). A later change to the notes runs that list like any other: the view is
   part of the notes page.

## Done when

`check_pdf.py` passes on each sheet with every warning judged; the audit's findings are applied;
the page images look right, every figure's axes labelled and each index line where its block
printed; the prune list is written, its answer logged or its `Sheet prune:` line in STATUS; the
published sheet's URL is in STATUS (an HTML sheet); it is committed. Or, with no sheet allowed, the Review view when PLAN.md gives it minutes: tagged in the
notes and the fragments, `fidelity.py`, `assemble.py` (within the minutes), `linkcheck.py --html`
and `verify_page.mjs` passing, both views' screenshots seen, the notes page republished to its URL,
and committed.
