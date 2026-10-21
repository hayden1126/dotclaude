# 07 Cheat sheet

Baseline as of 2026-10-20; changes only via `12-retro`.

The sheet the student may bring into the exam: one HTML document printed to PDF, built only when
the exam rules allow it (FB-130). It condenses the verified notes, organized by task, the way the
student will reach for it mid-question (FB-141). When PLAN.md includes a mock (`08-practice`),
this stage builds the mock sheet, `cheatsheet/<exam-slug>-mock.html`: it holds nothing derived
from the mock and is the one published. The final sheet adds the mock-derived items after the
attempt ("The final sheet" below, which 08 runs). Without a mock there is one sheet,
`cheatsheet/<exam-slug>.html` (FB-133).

## Step 1: Check the inputs

- CLAUDE.md's rules allow a sheet. Quote the rule in STATUS: its size, one side or two, whether
  it is collected and whether it must carry a name (FB-130). Not allowed: skip this stage and log
  it (as the build's last stage, or run alone, removing the `Build running` line).
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
   `<skill>/templates/agent-briefs.md`, section "Sheet gap scan", unnamed:
   - by content: the content variant, one agent per two or three notes sections, all at once.
     Pick from their reports (step 3) into the outline;
   - then by question type: one agent, the question-type variant (answer templates, pros and
     cons, a worked pattern per type), over the outline as it now stands, so it adds to the first
     pass's picks instead of repeating them. Pick again.
3. Picking: nothing a MANIFEST.md topic cut reaches, and nothing under a `Not on <exam>` banner,
   goes on a sheet. Every item must help cold. It states its purpose first, and a number says what
   it is for (FB-135). Nothing points into the notes: the student can't open them (FB-134). When the
   exam asks for proofs, a proof-techniques block goes in (FB-079). Log each suggestion you reject,
   and why, in `_build/logs/sheet-gaps.md`.

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
  above the floor (FB-142). `check_pdf.py` measures it.
- Name and id: never printed (FB-132). When the rules say the sheet is collected with a name,
  tell the student in this stage's report, and `08-practice` puts it first under the cram
  order's `## Tonight`.

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
   an orphaned heading, a gap under a table, a cramped table, a figure that lost its labels.
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
when it was built: it fills like any sheet. So the final sheet makes room for its items.

1. Copy `<exam-slug>-mock.html` (or the student's `.tex`) to `<exam-slug>-final.html` (or
   `.tex`). A later mock's misses start from the final sheet already built, never a new copy.
2. Add the mock-derived items (the student's misses, and the cold solver's conventions and the
   final-sheet items `08-practice` logged in STATUS for the mocks taken so far or for no mock),
   each verified like any other item. Room comes first from space a scope cut freed and left
   blank (below), then from lowering `--fs` toward the floor, then from replacing items the
   attempt showed the student doesn't need. Near a full page, new wording is no longer than what
   it replaces (FB-137).
3. Steps 4 and 5 for it, the audit limited to what changed. `diff` the two sheets: it shows the
   added items, what they replaced, the `--fs` line if it moved, any block moved between sides
   and wording cut at the floor, and nothing else.
4. Print it; it isn't published.

## After shipping

- Any change to a shipped sheet, a fix or an addition: show the student the draft first (FB-137;
  while a mock is untaken, as `08-practice` says in "Changing the notes or a sheet"); during
  study Q&A a dispatched writer makes it (hard rule 9; `09-tutor` step 5). Then step 5's audit
  limited to the change, step 4, and a republish of the published sheet as `06-site` step 6 says.
  A fix to a fact goes into both sheets; an addition the mock prompted goes into the final sheet
  only (FB-133).
- Space a later scope cut frees stays blank for the final sheet's items. Check which sections it
  would help, list them in STATUS, and ask the student when they are next here (FB-140).

## Done when

`check_pdf.py` passes on each sheet with every warning judged; the audit's findings are applied;
the page images look right; the published sheet's URL is in STATUS (an HTML sheet); it is
committed.
