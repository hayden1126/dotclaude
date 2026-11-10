# Changelog

Baseline as of 2026-11-10; changes only via `12-retro`.

One entry per round, oldest first, each written by that round's retro. A hub's copies of the
templates carry the `Baseline as of` date they were copied at; `11-next-exam` compares it with the
skill's and reads the entries since then to say what changed.

Each entry: `## Round <n> (<date>)`, then

- **Files:** each file the retro changed, with its new baseline date where it carries one;
- **Changes:** one line each, `<id>: <what changed, in a few words> (<evidence ids>)`;
- **Retired:** each id struck through, and why;
- **Backlog:** each row kept, dropped or picked for the next round, with its new status.

No quote, course name, person's name or outcome goes here: those stay private, behind the
evidence ids.

## Round 0 (2026-10-20)

- **Files:** every file of the skill, baseline 2026-10-20.
- **Changes:** the first version, built from two completed runs (sources A and B) and the session
  that planned run B (H): the rules in `feedback-log.md` (FB-001 to FB-190), the tool lessons in
  `lessons.md` (L01 on), and the critique's findings, unapplied, in `backlog.md`.
- **Retired:** none.
- **Backlog:** every row `open` but K42 (`shipped in v1`).

## Round 1 (2026-11-10)

- **Files:** `SKILL.md`, `references/CHANGELOG.md`, `references/backlog.md`,
  `references/feedback-log.md`, `references/lessons.md`, `templates/CHASSIS.md`,
  `templates/CONVERT.md`, `templates/MANIFEST.md.tmpl`, `templates/STYLE.md`,
  `templates/agent-briefs.md`, `templates/backbone.md.tmpl`, `templates/cram-order.md.tmpl`,
  `templates/hub-CLAUDE.md.tmpl`, `templates/notes-chassis.html`, `templates/PLAN.md.tmpl`,
  `workflows/00-intake.md`,
  `workflows/01-ingest.md`, `workflows/03-backbone.md`, `workflows/04-write.md`,
  `workflows/05-verify.md`, `workflows/06-site.md`, `workflows/07-cheatsheet.md`,
  `workflows/08-practice.md`, `workflows/09-tutor.md`, `workflows/10-polish.md`,
  `workflows/11-next-exam.md` and `workflows/12-retro.md`, each baseline 2026-11-10;
  `templates/compare-notes.py` and `templates/fidelity.py`, new, baseline 2026-11-10;
  `templates/verify-mock-key.py`, baseline 2026-11-10;
  `templates/chassis-shots/`, regenerated, with a new `-key` shot at each width and the 12
  `-review` shots of the Review view (`1280-light-review-*` and `390-dark-review-*`: top, map,
  key, wex and two subsections);
  `scripts/assemble.py`, `scripts/cram_check.py`, `scripts/extract_check.py`,
  `scripts/linkcheck.py`, `scripts/mock_leak.py`, `scripts/pw.mjs` and `scripts/verify_page.mjs`,
  which carry no date.
- **Changes:**
  - C1: the rail scrolls itself, never the page, so a long jump lands in WebKit (E1.C12, E1.G13,
    D1.C19). At the page's bottom the scroll-spy marks the last section (the source key) active,
    and `verify_page.mjs`'s `-key` step checks it.
  - L25: `scrollIntoView` cancels a smooth jump in WebKit only; `verify_page.mjs` runs the long
    jump there, and `--no-long-jump` skips it in the skill's own tests (E1.C12, E1.G13, D1.C19).
  - FB-014: a skill-file bug found in a hub is fixed or worked around there, logged in
    `_build/logs/skill-fixes.md` for the retro and offered to the other open hubs; hard rule 13
    (E1.C11, E1.C13, D1 (section 2), F1 (section 2)).
  - FB-109: `05-verify` step 3b, a cold reader per two or three sections, and its brief, counted
    in PLAN.md's 05 roster row (D1.C6, D1.C7, D1.C8, D1.C9, D1.C10, D1.C11, D1.C12, D1.C13,
    D1.C15, D1.C31, E1.C22, E1.C23, E1.C24, E1.C25, E1.C26, E1.C30, F1.C9, F1.C11, F1.C13).
  - FB-123: every citation links to its row in the page's source key, built by `assemble.py` from
    MANIFEST.md's Notes (what it is, up to a `;`), its new optional By column and the file name;
    `linkcheck.py` fails an unlinked citation (E1.C10, E1.C11, D1.C20).
  - FB-143: with no sheet allowed, the notes page's Review view, a toggle that shows the parts
    the notes tag `.rv` within the minutes of reading the student picks at intake, which
    `assemble.py` holds it to; `08-practice`'s "Changing the notes or a sheet" lists each published
    product and what a change does to it (E1.C17, E1.C18, E1.C21, F1.C3, F1.C5, F1.C8).
  - FB-158: the cram night opens with the notes page and mock links, a tier defined, and what is
    already read skipped (E1.C5, E1.C6, D1.C22).
  - FB-159: the cram night offers an Ed re-pull, and a key gate before each attempt (`08-practice`
    step 8.1) sends one background `writer` to recheck the untaken keys when the key checker fails,
    a leak check (the notes, the mock and final sheets, the mock pages, the cram order) hits a leak
    part, or a source or reference changed after the mock's `Key checked:` line; it reports part
    ids only, and skips a part that needs rewording. The student chose opening the keys over the
    spoiler risk a review logged (D1.C23, E1.C15, E1.C19, E1 (section 2)).
  - FB-191: before each publish after a notes change, `mock_leak.py --questions` checks the notes
    against every unattempted question set, and held passages wait in `_build/held.md` until the
    set is attempted (D1.C26, D1.C28, D1 (section 2), E1 (section 4), F1 (section 2)).
  - FB-192: tutor chat writes symbols as Unicode or plain text and coins no label; `09-tutor` step
    5.1 answers a definition from what it knows first, then checks the notes (D1.C14, D1.C16,
    D1.C17).
  - S33: each subsection states its depth label, carried by the notes, the cram order (checked by
    `cram_check.py`) and the exam-day map; a Must-know list ends with what is memorized and what is
    provided; FB-064's Home gains it (F1.C12, D1.C5, D1.C21, E1.C14, E1.C20, E1.C29).
  - FB-043: the exact `sha256sum` command before an original is deleted (D1.C27).
  - FB-089: notation the staff's own sheets use wins over a hub's own conventions, and the
    backbone's Conventions block lists each notation with its staff source (E1.C7).
  - FB-164: the definition-first answer, evidence only (D1.C30, E1.C28).
  - FB-052: `extract_check.py` reads an `.html` source with no slides container as text (D1.G5).
  - FB-154: `mock_leak.py` prints its result lines on stdout, usage errors on stderr (E1.G7).
  - FB-117: `verify_page.mjs` exits 2 on a page with step-throughs and no `--steps` (E1.G10,
    D1.G8).
  - K67, K68: `templates/compare-notes.py` and `templates/fidelity.py`, each with a self-test,
    copied by `05-verify` step 2 and `06-site` step 3; with K67, the Write brief puts trace and
    state names in backticks, as the comparison reads them, so dropping K67 reverts that line (D1
    (section 2), E1 (section 2), F1.G4, F1.G6).
  - K02: `assemble.py` renders the cram order into the notes page's exam-day map on every build,
    the map then open, and refuses a hand-written one; step 7.4 rebuilds and republishes the page
    (E1.C5, E1.C6, D1.C22).
- **Retired:** none.
- **Backlog:** K02, K67, K68 `trying (round 2)`; K70 to K75 `open`.
