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
  - FB-014: a skill-file bug found in a hub is fixed in the hub's copy, or, for a script or brief,
    worked around in the hub (a wrapper or flag under `_build/`), logged in
    `_build/logs/skill-fixes.md` for the retro (each entry dated), and offered to the other open
    hubs; hard rule 13, and the harvest reads the log (E1.C11, E1.C13, D1 (section 2), F1
    (section 2)).
  - FB-109: `05-verify` step 3b, a cold reader per two or three sections, and its brief, counted
    in PLAN.md's 05 roster row (D1.C6, D1.C7, D1.C8, D1.C9, D1.C10, D1.C11, D1.C12, D1.C13, D1.C15, D1.C31, E1.C22, E1.C23, E1.C24,
    E1.C25, E1.C26, E1.C30, F1.C9, F1.C11, F1.C13).
  - FB-123: every citation links to the page's source key, which `assemble.py` builds from
    MANIFEST.md: what the source is (its Notes, blank without them), who made it (MANIFEST's
    new optional By column, a Made by column when a cited row has one) and its file; `linkcheck.py`
    fails a citation with no in-page link, the chassis highlights a targeted key row, and
    `11-next-exam` removes a hub-local key, where `06-site` step 5 sends a build that refuses one;
    the key has three columns at most, so it fits a phone: the code, what it is with the file's base name under it (muted, small), and Made by
    (E1.C10, E1.C11, D1.C20).
  - FB-143: with no sheet allowed, the notes page's Review view, offered at intake with its length
    in minutes of reading, which PLAN.md's `Review view:` line records and `assemble.py` reads; the
    sheet questions are asked only when a sheet is allowed. A Review / Full notes toggle shows the
    Must-know lists, the exam-day map and the worked examples and pitfalls the notes tag `.rv`, and
    copies nothing. `07-cheatsheet`'s "Tag the review" tags by rank; `assemble.py` holds the view to
    its minutes at 150 words a minute, the map's cram block left out of the count (a reading list
    into the notes, not review text), and refuses a misplaced tag; a rebuild over the minutes is
    untagged, lowest-ranked first, before anything else (`07`, `08`, `09`), or, with no `.rv` tag
    left, given new minutes: asked of the student, or during an unattended build set and logged as
    a judgment call for the student to confirm (`07`'s opening, `08` step 7.4, `assemble.py`'s
    message); a section whose `Not
    on <exam>` or `Unverified` banner comes before its first `h3` is left out of the view whole,
    and a load or hash change to a hidden target switches to Full notes; CONVERT and `fidelity.py` carry
    the marker; `verify_page.mjs` checks and shoots both views; `11-next-exam` asks the minutes on a
    reopen whose exam allows no sheet and takes the finished exam's tags off; a `10-polish` scope cut
    untags cut material. The view replaces the separate condensed review page this round first
    built in `_build/review/`, whose copy of each fact drifted from the notes in review.
    `08-practice`'s "Changing the notes or a sheet" is the one list of the hub's published products
    (the notes page with its Review view, each sheet, the cram order, the questions and leak checks)
    and what each change does to them; `07-cheatsheet`'s "After shipping", a `09-tutor` patch, a
    `10-polish` pass and both `11-next-exam` source paths run it by reference. CONVERT maps a link
    to another published page, `[text](<url>#id)`, to a plain `<a href>` (E1.C17, E1.C18, E1.C21,
    F1.C3, F1.C5, F1.C8).
  - FB-158: the cram night opens with the notes page and mock links, a tier defined, and what is
    already read skipped (E1.C5, E1.C6, D1.C22).
  - FB-159: the cram night offers an Ed re-pull, and new staff answers take the source-added path;
    then one `writer` in its own worktree, from the new "Key recheck" brief, opens each untaken
    mock's key, fixes the parts the answer touches, reruns the key checker and reports part ids
    only, so no answer reaches the student's chat, which the hub CLAUDE.md's key rule now allows.
    A key gate before each attempt (`08-practice` step 8.1, never inside a build) spawns the writer
    when the key checker fails or STATUS gained a `Source added: ... done` or `Reference changed:`
    line after the mock's `Key checked: <slug> <date> at <sha>` line (git's order, not the dates),
    and a merge rewrites that line (or adds it, on an older hub; only step 4 adds one otherwise)
    to the writer's base (the head the session noted at the spawn, or the report's sha, never the
    current HEAD), so a `/clear`, a lost report or a failed merge leaves the check due with no state of its own; this replaced stored STATUS lines for a
    pending and a running recheck, which review found could start a writer mid-build. One writer
    runs at a time, in the background with its transcript unopened, its whole reply the JSON block
    (part ids and file names only), spawned once everything uncommitted is committed, and a merge
    with no report takes its `question` parts from the key checker's skipped list. Its
    merge takes only the untaken keys, the values file and `mock_key.py`, and a conflict is
    aborted, never resolved in the chat; a part whose question would need rewording goes into the
    key checker's new `SKIP`, its key answer replaced by a `Skipped tonight:` line, and onto the
    mock's cram order line, and a `blocked` report gets the main session's fix before any
    redispatch.
    The student chose opening the keys over the spoiler risk a review logged. It replaces a first
    form that opened no key, logging a recheck in STATUS for grading and a "bring it before
    marking" note on the mock's cram order line (D1.C23, E1.C15, E1.C19, E1 (section 2)).
  - FB-191: before publish, and before each republish after a notes change (an `08-practice`
    change, a `09-tutor` patch, a `10-polish` pass, either `11-next-exam` source path),
    `mock_leak.py --questions` checks the notes against every unattempted question set, skipped and logged when there is none; a set
    with no solutions row records its attempt as `no, attempted YYYY-MM-DD` in its own MANIFEST.md
    Answers cell, which `00-intake`, `11-next-exam` and `09-tutor` write and `05-verify` reads;
    held passages go to `_build/held.md`, whose quarantine line an older hub's CLAUDE.md gains,
    and return once the set is attempted
    (D1.C26, D1.C28, D1 (section 2), E1 (section 4), F1 (section 2)).
  - FB-192: tutor chat writes symbols as Unicode or plain text and coins no label; `09-tutor` step
    5.1 answers a definition from what it knows first, then checks the notes (D1.C14, D1.C16,
    D1.C17).
  - S33: each subsection states its depth label, carried by the notes, the cram order and the
    exam-day map; the `**Depth:**` line converts to a `p.connects` line (CONVERT,
    `fidelity.py`), and the map shows the label's words after each section's link; a Must-know
    list's last two items say what is memorized and what is provided; FB-064's Home gains it (F1.C12, D1.C5,
    D1.C21, E1.C14, E1.C20, E1.C29).
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
  - K02: the cram order at the top of the notes page, in the exam-day map, which then renders open.
    `assemble.py` renders the map's cram block from `practice/cram-order.md` on every build and
    refuses a hand-written one, in place of the hand-kept copy `08-practice` step 7.4 first
    rewrote. Step 7.4 now rebuilds and republishes the page (the handoff is step 7.5), run on its
    own after step 7.3 and step 8.4; inside "Changing the notes or a sheet", item 3's one rebuild
    carries a cram order change, and a `09-tutor` patch's cram row is fixed by the main session at
    the merge. The sample hub's map renders open with a cram order and depth labels, and the
    reference shots show it (E1.C5, E1.C6, D1.C22).
- **Retired:** none.
- **Backlog:** K02, K67, K68 `trying (round 2)`; K70 to K75 `open`.
