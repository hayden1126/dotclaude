# 06 Site

Baseline as of 2026-11-10; changes only via `12-retro`.

The site is one long notes page, `_build/notes.html`, built from the verified notes and published
as a private artifact (FB-110). Converters turn each notes file into an HTML fragment in parallel;
the main session alone generates the step-throughs, writes the exam-day map, assembles the page,
checks it in a browser and publishes it.

## Step 1: Check the inputs

- `05-verify` is done: everything in its "Done when" holds (`selftest.py` prints `ALL PASS`, no
  `TODO-VERIFY` is left, the findings are settled, `linkcheck.py` exits 0, the fixes are
  committed). The self-test is what vouches for the step-throughs' traces, and `assemble.py`
  refuses a fragment that still holds a `TODO-VERIFY`.
- `_build/CHASSIS.md` and `_build/CONVERT.md` are the hub's copies of the skill's templates.
- `_build/chassis.html` is a copy of `<skill>/templates/notes-chassis.html` with its placeholders
  filled from CLAUDE.md's exam facts (course, exam, the date, time, allowed materials) and
  MANIFEST.md's rows (the scope), and its opening comment dropped. `assemble.py` refuses a
  placeholder left in it.
- Plain-text notes (`04-write`, step 6) skip this stage: the student reads the Markdown.

## Step 2: Generate the step-throughs

A figure the backbone's shortlist marks `step-through` is the main session's. A script,
`_build/verify/stepthroughs.py` beside the checker, imports the checker's own functions (the
module `examples.py` runs), runs them on the figure's instance, and writes from that one trace
(FB-117: no frame is typed by hand, so the student steps through the trace the self-test vouches
for):

- `_build/frag/step-<fig-id>.html`: the figure, in CHASSIS.md's step-through form (its SVG,
  caption, `.fig-controls` buttons and status line), showing the first frame;
- `_build/frag/step-figs.js`: every handler, `window.NotesFig['<fig-id>']`, with the frames
  embedded as data;
- `_build/frag/steps.json`: what the browser check expects of each figure,
  `{"<fig-id>": [{"act": "<mode>", "frames": <presses of Next to the last frame>, "final": "<text
  the last frame shows>"}]}`, one entry per mode (`act` left out for a figure with one).

Start from `<skill>/templates/stepthrough-example/` (a two-mode figure, its handler and its
`steps.json`). Rerun the script whenever the checker changes, so a convention change regenerates
every figure.

## Step 3: Convert, one agent per section

Load the delegation skill first (FB-003). Fill one brief per notes file from
`<skill>/templates/agent-briefs.md`, section "Convert", and spawn them all at once, unnamed (L45),
each writing its own `_build/frag/secN.html`. Each converter draws its section's static figures
(every tree or graph example gets one, never ASCII: FB-115) and leaves step-through markers in
place. Converters use only the chassis's classes (FB-120).

When they return, `git status` names nothing but the fragments and steps 1 and 2's files (a
converter that ran `assemble.py` left a page: delete it; step 5 builds it). Compare each fragment
with its notes file by script, never by eye: copy `<skill>/templates/fidelity.py` to
`_build/verify/fidelity.py`. First `python3 -I _build/verify/fidelity.py --self-test` must print
`SELF-TEST OK`: a clean pair passes, and a dropped sentence, a changed number, two swapped steps
and a dropped citation planted into each fragment are caught. `python3 -I
_build/verify/fidelity.py` then compares headings, text, citations, links, callouts and steps as
CONVERT.md maps them, prints one line per difference with its section, and exits 1 on any: fix
the fragment and rerun it. Then read each report's list of bare references: wire each in the
notes (a link with the backbone's id; a mention inside its own subsection stays text, S12), rerun
`linkcheck.py`, and make the same edit in that section's fragment (a larger change: have the section
converted again), then run `fidelity.py` again on the sections touched.

## Step 4: The exam-day map

Write `_build/frag/examnav.html` from the backbone's "How it's tested" table (FB-113): a
`<details class="examnav">` whose summary names it, then in its `.ebody` a `.efound` read-first
line (the conventions that change every answer, linked), a `.egrid` of `.eq` groups (an `.eqh`
heading, then one `<li>` per question shape: the shape in `<b>`, its section as an `xref`, its
practice questions), and an `.edrill` line naming what to drill hardest. Every link uses a
backbone id. A shape that tests only what a topic cut takes out (the backbone's Conventions cut
lines) stays out of the map. Each section the map names carries its depth label (S33) beside its
`xref`: the label's words alone (Know cold, Use, Recognize), in parentheses after the link, plain
text, without the statement it rests on: `<a class="xref" href="#sec-2-walks">§2.2 Walks</a> (Use)`.

Once `08-practice` step 7 has written the cram order, the map opens with it (K02) and renders
open, `<details class="examnav" open>`, so the cram order shows at the top of the page: one `.eq`
group per tier before the question shapes, its `.eqh` the tier's name and minutes, one `<li>` per
row (its one thing in `<b>`, its section as an `xref` to the section's anchor, its depth label),
then the skip list and the Out of time line in an `.edrill` line. Its mock lines and `## Tonight`
stay in `practice/cram-order.md` only. That file is the one source: the map's copy is rewritten
from it each time it changes (`08-practice` step 7.4), never edited apart. Before the cram order
exists the map stays closed, with no `open` attribute.

## Step 5: Assemble and check

From the hub root:

1. `python3 -I <skill>/scripts/assemble.py` writes `_build/notes.html`. It refuses a missing or
   misnamed fragment, a script, style or unknown class in one, and a FIG marker with no
   step-through. It ends the page with a source key built from `MANIFEST.md` (a row per code the
   page cites, each citation linked to its row), and refuses a citation whose code has no
   `MANIFEST.md` row.
2. `python3 -I <skill>/scripts/linkcheck.py --html _build/notes.html`: every in-page link
   resolves, and no id repeats.
3. `node <skill>/scripts/verify_page.mjs _build/notes.html _build/shots --steps
   _build/frag/steps.json` (leave `--steps` out when there are no step-throughs) with
   `allowed_domains` cdnjs.cloudflare.com, fonts.googleapis.com and fonts.gstatic.com (L20 to L22).
   It checks math (TeX errors too), overflow (with the worked examples and the map opened too),
   links, fonts, closed examples, scroll-spy and every step-through's runs, forward and back, at 390
   and 1280 px in light and dark, and saves screenshots to `_build/shots/` (gitignored). Its long
   jump clicks the rail's last entry from the top and its first from the bottom, and checks each
   heading lands at the top, in Chromium and in WebKit, Safari's engine, where a jump the rail cuts
   short shows (C1); without Playwright's WebKit it prints a WARN line naming `npx playwright
   install webkit`, for the user to run in their terminal. A build never passes its
   `--no-long-jump`, which is for the skill's own tests. It finds
   Playwright in `_build/node_modules/`, the hub's `node_modules/` or npm's global root, or at the
   package directory `EXAM_PREP_PLAYWRIGHT` names. With none, it says so and exits 2: install it
   once outside the hub's tracked files (`npm install playwright` in `_build/`, whose
   `node_modules/` and `package*.json` are gitignored), with `allowed_domains` registry.npmjs.org
   (a sandbox denial names any other host it needs). Its browser comes from the user's terminal:
   sandboxed Bash can't write Playwright's browsers dir, so ask them to run `npx
   playwright@<the version _build/ installed> install chromium-headless-shell` there.
4. Look at the screenshots yourself against `<skill>/templates/chassis-shots/`: the checks pass on
   a page that still looks wrong.

Fix a failure at its source (the notes, a fragment, the map), never by editing `notes.html`, and
rerun from step 1.

## Step 6: Publish

- Publish `_build/notes.html` with the Artifact tool, private (FB-110), then check its sharing
  setting (FB-118), and put the URL in STATUS.
- Publish from the session that built the page. A republish from another session must first read
  the whole live copy, in chunks, and diff it against the build (FB-122, L30). If the
  auto-mode classifier refuses an Artifact call once, repeat the identical call once (L31).
- A deploy to the student's own site, if they have one, waits for their explicit go after they
  have reviewed the page (FB-114).
- A screenshot bug report from the student is reproduced with their platform's scrollbars, not
  only headless (FB-119, L12).

## Done when

`assemble.py` exits 0; `linkcheck.py --html` and `verify_page.mjs` pass; the screenshots match the
chassis's look; the page is published privately and its URL is in STATUS.
