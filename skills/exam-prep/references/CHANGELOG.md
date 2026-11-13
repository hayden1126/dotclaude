# Changelog

Baseline as of 2026-11-12; changes only via `12-retro`.

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

## Round 2 (2026-11-12)

- **Files:** `SKILL.md`, `references/CHANGELOG.md`, `references/backlog.md`,
  `references/feedback-log.md`, `references/lessons.md`, `templates/CHASSIS.md`,
  `templates/CONVERT.md`, `templates/MANIFEST.md.tmpl`, `templates/PLAN.md.tmpl`,
  `templates/STYLE.md`,
  `templates/agent-briefs.md`, `templates/backbone.md.tmpl`, `templates/cram-order.md.tmpl`,
  `templates/hub-CLAUDE.md.tmpl`, `templates/mock-page.html`, `templates/notes-chassis.html`,
  `workflows/00-intake.md`, `workflows/01-ingest.md`, `workflows/02-extract.md`,
  `workflows/03-backbone.md`,
  `workflows/04-write.md`, `workflows/05-verify.md`, `workflows/06-site.md`,
  `workflows/07-cheatsheet.md`, `workflows/08-practice.md`, `workflows/09-tutor.md`,
  `workflows/10-polish.md`, `workflows/11-next-exam.md`, `workflows/12-retro.md`,
  `templates/verify-selftest.py` and `templates/verify-set-key.py`, each baseline 2026-11-12;
  `templates/WATCH.md` and `templates/videos-addon.html`, new, baseline 2026-11-12;
  `templates/chassis-shots/`, regenerated, with new `-pin` and `-review-pin` shots and two new
  figure shots (`-fig-1-slide`, `-fig-2-triangle`) at each width;
  `scripts/videos.py` and `scripts/verify_videos.mjs`, new, and
  `scripts/assemble.py`, `scripts/coverage_check.py`, `scripts/cram_check.py`,
  `scripts/extract_check.py`, `scripts/mock_leak.py`, `scripts/mockpage.py`,
  `scripts/verify_page.mjs`, which carry no date. Outside the skill, the tests
  `tests/exam_prep/test_agent_briefs.py` and `test_videos.py`, new, and `test_assemble.py`,
  `test_coverage_check.py`, `test_cram_check.py`, `test_extract_check.py`, `test_linkcheck.py`,
  `test_mock_leak.py`, `test_mockpage.py`, `test_set_key.py`, `test_skill_files.py`,
  `test_verify_page.py` and `test_verify_templates.py`, with their fixtures, changed with them.
- **Changes:**
  - FB-124 and L26: the theme chrome, CHASSIS C2 (themed scrollbars, an opaque page track), C3
    (a fixed theme icon with no words) and C4 (full screen where granted, the F and T keys), on
    the notes page and the mock page, judged inside a light-scheme parent frame; `verify_page.mjs`
    checks it on both (I3.C9, I3.G10, I2.C32, J1.C5, J1.C6, J1.C7, J1.C9, J1.C10, J1.G6).
  - FB-111: every section's own dark-mode highlight band, set by `assemble.py` (J1.C11, I3.C9).
  - FB-015: a check new to the skill passes an existing hub's form with a warning naming the pass
    that upgrades it: a cram order with no depth labels, a backbone with no `Diagram-taught`
    lines, or a backbone section marked `Diagram-taught: pre-S11` (a reopened hub's older
    sections, which `11-next-exam` marks, or those a partial `10-polish` figure pass leaves, which
    it marks; a covering figure pass sets `yes` or `no`) builds with a WARN
    (I3.C8, I3.G8, J1.G5, I1 (section 2)).
  - FB-123: citation codes now match their MANIFEST.md row in any case, silently, the source key
    keeping the row's spelling (I3.C8).
  - FB-056: official solutions move out of the extracts into `_build/solutions/`, one file per
    set, `_build/solutions/<name>.md` beside its extract `_build/extract/<name>.md`, holding one
    block per question part of the set plus an answers doc's page blocks (`02-extract`, "The
    solutions file"). The set's extract agent writes it, or, for an answers file that solves
    several sets, that file's own agent writes each set's part blocks in that set's file, plus its
    own pages, in full, in `_build/solutions/<doc id in lower case>.md` (hard rule 6: an agent may
    write several files, and no file is written by two agents). Every solutions block has one home
    file: a set's part or stem blocks beside its extract, an answers file's page or section blocks
    in the one set's file it solves or, when it solves several, in its own file, and a self-keyed
    doc's key blocks beside its own extract; a set's home is the file beside each extract holding
    any block of it, a page, section or slide block included, and a block whose set no extract
    holds fails `NO HOME FILE`. MANIFEST.md gets a Key column, which
    `01-ingest` writes after looking at the file and `extract_check.py` reads whole: `for HW1,
    HW2` for a separate answers file, `pp. 7-9, 11` or `p.N`, `inline`, or `sections: Marking
    scheme, Answers` for a source without pages, whose key sections are the blocks with exactly
    those locators. Only those pages or sections go to the solutions file, and a past exam's
    cover, rules and formula sheet stay in the extract. Notes are free text that nothing parses.
    `extract_check.py` checks the pairing and fails a solution or answers page left in an
    extract, a block outside its home file (`WRONG SOLUTIONS FILE`), and a Key
    cell that is missing, unread, names no doc, names its own row, sits on a row without
    answers, names sections on a paged doc, pages on an unpaged one or a section with no block
    (`NO KEY`, `UNREAD KEY`, `KEY NAMES NO DOC`, `KEY NAMES ITS OWN DOC`, `KEY WITHOUT ANSWERS`,
    `SECTIONS KEY ON A PAGED DOC`, `PAGES KEY ON AN UNPAGED DOC`, `KEY SECTION NOT FOUND`); a
    locator naming a key section followed, after any spaces, by nothing, a character that is no
    letter or digit, or `Q` and a digit is key material (`Key formulas` under `sections: Key` or
    `Marking scheme 2` is not), and so is one naming a key section whatever page reference it
    carries (`[PE3 Marking scheme p.2]`); a Key name with a page reference (`sections: Answers
    p.4`) matches its block. It warns on an
    `Answer:` line in a solved doc's extract, and `extract_check.py --parts` feeds `05-verify`'s
    PARTS (FB-100). A set's attempt is recorded in that set's own row only, `no, attempted
    YYYY-MM-DD` (no key of its own) or `yes, attempted YYYY-MM-DD` (a doc holding its own key);
    a separate answers file's row stays `yes`, since it may solve several sets, and the notes
    quote a set's official solution only once its own row says `attempted` and every set its
    answers file solves is attempted. `05-verify` step 5's questions check reads each unattempted
    set's extract and its solutions file when it has one, plus a multi-set answers file's own file
    while any set it solves is unattempted, never an attempted set's own file, and every hit is a
    blocker. An erratum's corrected value sits in its part's solutions block, and the
    backbone names its doc and part only. Answer-blind briefs read the extracts and never open
    `_build/solutions/`; the writers, section reviewers, checker and tutor read both. An older
    hub's extracts with solutions inline, or its answers notes in Notes, aren't supported
    (I3.C18, I3.G9, I2.G10).
  - FB-055: a value still illegible on a 300 dpi crop is written `(illegible at 300 dpi:
    <what>)` by the main session, which `extract_check.py` lists by file and line without
    failing, noted in STATUS and asked once no `Build running` line stands; the value the
    student gives replaces the mark, then `extract_check.py` and the self-test rerun, and until
    then the self-test skips that part, naming the mark (round 9 and round 10 reviews).
  - FB-191: `mock_leak.py`'s questions mode drops only the extract brief's own note lines (a
    `Pages:` line of cites alone, `**Shape:**`, `**Conventions:**` and the closing `Coverage:`
    line), so question text on any other `Pages:` or `Coverage:` line is checked (round 6 review).
  - FB-193: each cram row names its needs, and the cram order gets a Read already line, which
    `cram_check.py` checks (J.O, I1.C15, I1.C18).
  - FB-194: the watch list: `templates/WATCH.md`'s rules W1 to W39, `videos.py`,
    `verify_videos.mjs`, `08-practice`'s "Watch list", intake question 6 (and the reopen's
    question 7), PLAN.md's line and three briefs; the rankers search and judge in two parts and
    the main session fetches between them (L07, L02), in a build with `allowed_domains` only,
    into a fetch log started fresh each run; a gap wave writes its own `-gaps` candidate and
    ranking files, which the merge and the cut-loss reviewer read too, and a rerun in the same
    exam takes the last run's candidate, ranking and annotation files and merge log out first,
    so neither reads them as its own; `11-next-exam` step 5
    archives it with the finished exam and lists its URL under `Earlier exams:`, so a new run
    publishes to a new URL; run alone it waits while a `Build running` line stands, a polish
    pass's included, never on a finished pass's `Polish:` line (hard rule 1); L72 to L75 are its tool lessons, which W36 to W39 cite
    (I.O, I1.C5, I1.C6, I1.C7,
    I1.C9, I1.C13, I1.C14, I1.C15, I1.C16, I1.C17, I1.C18, I1.C25, I1.C26, I3.C2, I3.C3, I1.G4,
    I1.G5, I1.G6, I1.G7, I3.G7).
  - FB-144, FB-145, FB-146: the sheet's index, its figure pass with every axis labelled, and its
    prune list, which the stage never asks in any run (hard rule 1): its STATUS line is asked
    once a stage run alone has ended, or at `08-practice` step 8's opening; FB-141 drops the cram order's map of the sheet, which the index replaces (I.O,
    I1.C21, I1.C22, I1.C23, I3.C5).
  - FB-164, FB-192: tutor answers short by default in labelled bullets, symbols defined at first
    use, an overloaded letter named apart, no LaTeX delimiters or HTML tags in chat (J1.C4, I1.C10,
    I1.C24, I1.C25, I1.C27, I1.C28, I2.C13, I2.C14, I3.C3).
  - FB-166, FB-160: a gap goes to the tutor log at once as a `proposed` line, offered with the
    others as one patch every five questions; a pointer names the page's section, never a file
    line (I1 (section 2)).
  - FB-195: a declined mock, `08-practice` step 8 and `07-cheatsheet`'s final sheet; at a reopen,
    `11-next-exam` step 5 moves its STATUS line to the archive with the attempts and takes out
    the round's other lines waiting for the student (the prune list's, the set minutes', the
    figure shortlist's) (I1.C2, I3.C1).
  - FB-158: the cram night names the one sheet to print, and the cram order's Tonight section is
    the exam-morning card; intake question 4 asks the room and what is banned, and so does the
    reopen's (I1.C1, I1.C29, I3.C24).
  - FB-182: the graded previous exam read once into a shape file at a reopen (the one `out` row
    PLAN.md's Sources line lets a session open), and the tutor log's Patterns labelled one-exam
    evidence (I3.C13, I3.C17, I3.C26, I2.C26, I2.C27, I3.C14, I3.C15, I3.C16).
  - FB-071: section reviewers check the notes' wording against the answer files (I3.C20).
  - FB-159: a staff post that states only the exam's format is no source added (I3.C11).
  - FB-118 and L30: STATUS records each artifact's owner and sharing state; a URL that can't be
    updated gets a new private artifact, and the old one is marked stale (I3.C6, I2.C29, I2.C32,
    I2.G1, I2.G2, I3.G5).
  - FB-095: `assemble.py` refuses only tool-call markup, a feedback-log id in parentheses and a
    CHASSIS id right after `CHASSIS` in the notes, and only warns on a bare STYLE, lesson, backlog
    or CHASSIS id, one after `rule` among them, which a course writes for its own things, so a
    rebuild never fails on course text (FB-015); STYLE S16, `04-write` and the Write brief say so
    (J1 (section 2)).
  - FB-094 and FB-075: STYLE S34, the concise box (CONVERT's box, CHASSIS C6, the Review view
    shows each box untagged and counts it toward its minutes, `07-cheatsheet` setting measured
    minutes when the boxes alone pass them, a build's set minutes asked at `08-practice` step 8's
    opening, a stage run alone's once it has ended, a rebuild's after step 8.4 at once, intake question 5 and FB-143 saying so, `10-polish`'s
    box pass, the briefs), and S18 reworded "Concise, never
    compressed" (I1.C10, I3.C3, J1.C4, I2.C13, I2.C14, I2.C15, I1.C24).
  - FB-062, FB-115 and FB-125: STYLE S11 widened to diagram first, `03-backbone` step 5's sweep
    and `Diagram-taught` lines (its shortlist logged in STATUS as one `Figure shortlist:` line,
    and the rows of the sections each run swept in `_build/logs/figures.md`, the rows still
    waiting kept, while the build's or `11-next-exam`'s source
    path's `Build running` line stands, and shown to the student when run alone or in a
    `10-polish` figure pass, offered at `08-practice` step 8's opening or, after `Stage 08 built`, at
    the source path's step 5 report), intake's and
    PLAN.md's Figures default (a step-through for every drilled trace), `coverage_check.py`'s
    figure floor, CONVERT's slide-image figure (its crops in `_build/img/`, gitignored as renders
    under hard rule 5, FB-011, the line added to an older hub's `.gitignore` before the first crop
    at `04-write` step 4.5, a file already tracked under a line `11-next-exam` step 5.2 adds taken
    out of the index, and a stopped source's crops deleted with its renders), `10-polish`'s
    figure pass (which can cut a figure the build drew, and takes the rows it settles out of the
    log and the STATUS line's count), and CHASSIS C5, a linked figure pinned in a panel (F.O,
    J1.C12, I1.C19, I1.C21, I1.C22, I3.C5, F1.C4).
  - FB-061: `coverage_check.py` reads a dotted sub-part (J1.G4).
  - L22: intake records the Playwright path on the hub CLAUDE.md's Tools line (I1.G3, I2.G12,
    I3.G3).
  - L76: on WSL a file opens for the student with `explorer.exe` and `wslpath -w`, sandbox off,
    its exit status 1 normal (I1.C3, I1.G12, I2.C21, I2.G6).
  - K75: `12-retro` step 2 takes a parent folder's transcripts with their own window, filtered by
    content (a shard kept only when it names the hub, each drop logged); step 3 gives a hub with
    long records a records-only reader, spawned beside its shard readers, which then skip the
    records (round 1 retro, I3).
  - The chassis: the column gets room at its foot so the last subsection reaches the spy line,
    and the closed drawer drops its shadow (part of K61).
  - SKILL.md: the watch list in the stage map, `_build/solutions/`, `_build/img/`,
    `_build/watch/` and `_build/videos/` in the hub layout, and the solutions files in hard
    rules 4 and 6.
- **Retired:** none.
- **Backlog:** K26, K52, K70 and K75 `kept (round 2)`; K02, K67 and K68 `trying (round 3)` (no hub
  had them this round); K29 and K61 stay `open`, each partly covered (CHASSIS C3, the drawer's
  shadow); K77 to K83 new and `open` (I1.C20, I3.C4, I1.C19, J1.C12, I1.C11, I3.C7, I3.C25,
  I2.C25, I2.C1, I2.C11, round 1 review, r8-2).
