# Feedback log

Baseline as of 2026-11-12; changes only via `12-retro`.

Every rule the skill encodes came from a correction or a stated preference in a past run. This log
traces each one to its evidence. Ids are stable, so a hub doc that cites `FB-073` keeps pointing at
the same rule: none is renumbered or reused. A new rule (`12-retro` step 6) takes the next free
number in its stage's block (the gap before the next block's first id), else the next after the
highest id, and sits in its stage's section. A retired rule keeps its row, struck through
(`| ~~FB-073~~ | ~~<its rule>~~ | ... |`), its last cell ending `retired (round N): <why>` and
naming the id that replaces it, if one does.

- **Evidence** cites `<source>.<item>`, such as `A1.C23` (source A1, correction 23) or `B3.G7`
  (gotcha 7). The sources are harvest reports of two completed runs (A and B) and the session that
  planned run B (H); a retro gives each hub-exam of its round the next free letter, skipping C, G,
  K, L and S, which would read as other ids, then `AA`, `AB` and on after Z (`12-retro` step 1).
  They quote the student verbatim, so they stay private and are not shipped. A maintainer who has
  them reads `~/scratch/exam-prep/evidence.md` for the index. `skill test P<n>` cites pressure
  scenario n of the skill's own tests before release, with the student's ruling on it (private too).
- **Home** is where the rule lives in the skill: a STYLE or CHASSIS rule (`S4`, `C2`), a workflow
  step (`w04`), a template (`t:cheatsheet`) or a script (`linkcheck.py`). `12-retro` keeps this
  column current.
- **Stage** tags use the workflow numbers. `all` means a hard rule in SKILL.md.

## all: cross-cutting

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-001 | After the plan is approved, run unattended. Log judgment calls in the hub's STATUS instead of asking. | SKILL | B1.C1, B4.C5, H1.C4 |
| FB-002 | Make every stage resumable: check what is already on disk and start at the first unfinished stage. All state lives in files. | SKILL | B1.C2, H1.C8 |
| FB-003 | Load the delegation skill before the first spawn. Parallel within a wave, no file written by two agents, unnamed spawns, merges single-threaded. | SKILL | B1.C3, B4 (hard rules), A2.G1 |
| FB-004 | Record a ship-priority order at intake (notes site, then cheat sheet, then mock) and cut from the bottom when time runs short. | w00 | B1.C4, B4.C5 |
| FB-005 | End each work block with the handoff skill and a local commit. Never push. Course material stays untracked; the hub's progress files are tracked. | SKILL | A1.C11, A2.C7, B1.C6, B2.C7, B3.C36, A4.C8 |
| FB-006 | Persist every build source into the hub. The session scratchpad does not survive a clear. | SKILL | A1.C11, A4.C2 |
| FB-007 | Keep the planning session and the execution session apart. Everything durable is on disk before the planner stops. | w00 | H1.C9, H1.C14 |
| FB-008 | Before concluding that something does not exist, read the hub's STATUS and PLAN. STATUS lists every published artifact's URL. | SKILL | A3.C19, A3.G6 |
| FB-009 | Put numbered options in the visible message. Never refer to options the student can't see. | SKILL | A1.C10 |
| FB-010 | Start a new course from the latest baseline with every past correction applied up front, not rediscovered as late polish. | SKILL | H1.C2 |
| FB-011 | Course material is copyrighted: `sources/` and rendered pages are gitignored, the hub repo stays local, and no remote is added without the student's go. | SKILL, t:hub | B4.C8, A4.C8 |
| FB-012 | Never state a prediction about the exam without a source. Record the instructor's exam-format statement in the hub and cite it. | w00, w09 | A3.C10 |
| FB-013 | When the student asks to skip the extract, the backbone or the reviews for an added source, push back once (what it costs, how long the full path takes), commit a `Skip asked` line in STATUS, and wait, writing no notes. Asked again, add it as notes only, in one commit with its MANIFEST row and an `Unverified:` STATUS line; values from the checker's output or quoted with a citation, never computed; an `Unverified` banner on the material and the page; off every sheet, out of the mocks' plan and the cram order's reading rows, and out of walk-throughs until verified. The addition fences itself like a build. It refuses a doc whose MANIFEST row would mark it a set the student hasn't attempted or an answers file solving one (an Answers `yes` row with its own key, an empty or unread Key, or a `for` key naming an unattempted set; or a set an answers row names), or any other question doc the student hasn't attempted (Answers `no` included, which the script counts as a set only once extracted), since the questions check needs its extract: that ends the addition with nothing added, logged, and the doc goes through the full path. Its row's Key cell still gets the Key checks that read MANIFEST alone. Where the ask comes (a tutor tab, a build, a patch open, a mock untaken) decides when either happens. | SKILL, w11, w02, t:convert, extract_check.py | skill test P1 |
| FB-014 | A bug found in a hub that lives in a skill file (a template, the chassis, a script, a brief) is fixed in the hub's copy, or, for a script or brief, worked around in the hub (a wrapper or flag under `_build/`), then logged in `_build/logs/skill-fixes.md` for the retro, each entry starting with its date (YYYY-MM-DD), then what, where and the hub's diff, and the session offers to relay the fix to the other open hubs that use that file. | SKILL, w12, t:briefs | E1.C11, E1.C13, D1 (section 2), F1 (section 2) |
| FB-015 | A check added to the skill accepts the form an existing hub already holds: it passes it with a warning that names the pass that upgrades it, and never blocks a rebuild mid-exam. Round 2's: a cram order with no depth labels, a backbone with no `Diagram-taught` line at all, and an older backbone section marked `- Diagram-taught: pre-S11` (a reopened hub's, or one a `10-polish` figure pass over other sections leaves); once any section carries a line, a section with none fails. | w03, w10, w11, t:backbone, assemble.py, cram_check.py, coverage_check.py | I3.C8, I3.G8, J1.G5, I1 (section 2) |

## 00-intake

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-020 | Ask every intake question up front, in one round, before the plan. After approval, ask nothing more. | w00 | H1.C4, A1.C1, A1.C2 |
| FB-021 | Settle the scope authority first: does the graded work (homework, practice exam) mirror the exam? If yes, scope follows it. If no, cover the full scope and write mock questions in shapes beyond the review. Check a narrowed scope against the sources before committing to it. | w00 | A1.C1, A1.C2, H1.C3, A4.C10 |
| FB-022 | A question the student always answers with the default is a default, not a question. Don't ask what an exam-details file already says. | w00 | H1.C5, H1 (section 5) |
| FB-023 | Ask which files belong to which exam. Material for a later exam is copied raw, listed as reserved in MANIFEST, and never opened. | w00, w01, t:manifest | H1.C7, B1.C5, B4.C8 |
| FB-024 | Ask for the exact last in-scope slide and whether its number is the PDF page or the printed slide number. Keep the scope in one place (the hub's MANIFEST rows; CLAUDE.md and PLAN.md point to them) and propagate every change to it. | w00, t:manifest | B3.C3, B4.C14, B4.G16 |
| FB-025 | Record the course logistics in the hub: grade weights, how many homeworks and exams, late policy, the exam-format statement, dates. When a fact isn't recorded, say so rather than guess. | w00, t:hub | A3.C11 |
| FB-026 | Intake fixes the deliverables and their shape: notes site built from markdown, cheat sheet if allowed, mock with a separate key, depth weighted by how the exam tests, figures static plus a few step-throughs. | w00 | B4.C1, B4.C2, B4.C3, B4.C4, H1 (section 5) |
| FB-027 | Intake ends with a written plan the student approves, then hub setup. Expect several plan rounds; fold each refinement into the plan file before showing it again. | w00 | H1.C15, A1.C4 |
| FB-028 | Before launch, audit the plan for visual design, pedagogy, structure, enumeration and cross-references. Written rules beat "reuse the look". | w00 | H1.C10, H1.C11 |
| FB-029 | When intake needs a file the student hasn't provided yet, wait for it. Don't continue past the question. | w00 | H1.C6 |
| FB-030 | Write for a student who may have skipped the lectures: assume no prior exposure. | S14, w04 | A1.C1 |

## 01-ingest

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-040 | Never use WebFetch on slides: it summarizes and drops formulas and slide numbers. Fetch raw HTML with curl and slice it; render PDFs page by page to image and text, and view the image when the text layer is thin. | w01, SKILL | A1.G1, A4.G1, B4.G15, H1.G2 |
| FB-041 | A deck is not a lecture: cut extraction boundaries by content. Never split one slide between two agents. | w01, w02 | A1.C3 |
| FB-042 | Select source files by name. Never glob a downloads folder, which holds unrelated secrets. | w01 | H1.G8 |
| FB-043 | Delete originals only after a SHA-256 match against `sources/`. After that, STATUS says `sources/` is the only copy. | w01 | B1.C8, B2.C8, B4.C17, D1.C27 |
| FB-044 | MANIFEST has one row per document: id, file, pages, in, out or reserved, and a note. Take counts from disk. | w01, t:manifest | B1 (stage 01), B4 (section 5a) |

## 02-extract

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-050 | Extracts are organized by source unit; notes are organized by topic. | w02 | A1.C6 |
| FB-051 | Capture provenance once, at extraction: the base location once per file, the slide or page per fact, and a verbatim anchor phrase for key formulas and tables. | w02, t:briefs | A1.C7 |
| FB-052 | Extractors view every page image as well as the text, write diagrams as data, and flag what they can't read. The run's report states image coverage per deck. | w02, t:briefs, extract_check.py | B1.C7, B4 (stage 02), D1.G5 |
| FB-053 | One whole deck per agent. Split a big deck at a section divider with a three-page overlap. | w02 | B4 (stage 02), H1 (stage steps) |
| FB-054 | Fan out wide for raw extraction. A stage that carries cross-references works from a fixed id registry or stays single-threaded. | w02, w04 | A4.C4 |
| FB-055 | Check small, rotated or crowded labels on a higher-resolution crop before using the value. | w02, t:briefs, extract_check.py | B1.G9 |
| FB-056 | Official solutions live only in `_build/solutions/`, `_build/solutions/<name>.md` beside each `_build/extract/<name>.md` that needs one, written by the set's extract agent (an answers file that solves several sets gets its own agent, which writes each set's part blocks in the file beside each extract holding them plus its own pages, in full, in `_build/solutions/<doc id in lower case>.md`; no file is written by two agents), one block per question part of the set (its `Solution [` line or `No official solution.`) plus an answers doc's page blocks; the extracts hold none. MANIFEST.md's Key column, read whole (`for HW1, HW2`, `pp. 7-9, 11`, `inline`, `sections: <name>, <name>`), says what each answers doc solves and where its key sits; Notes are free text. Every solutions block has one home file by what it is, and `extract_check.py` fails a part with no solutions block, a block outside its home file, a solution or answers page left in an extract, and a Key cell that is missing or unread. An answers file solves only in-scope sets: a Key cell naming a `pending`, `reserved` or `out` set fails `KEY NAMES A SET NOT IN SCOPE` (drop the set and cut its pages from the answers file's Scope, or give the answers file the set's Scope, the only fix when it solves that set alone). The questions check's file list comes from the script, never by hand: `extract_check.py --leak-files` prints it (every extract holding a block of an unattempted set, every existing home solutions file of one, and a multi-set answers file's own file while any set it solves is unattempted, as question files; every other extract allowed), and `mock_leak.py --hub .` runs the check with it, reading extracts and solutions files (and, beside the extract, the rendered text of a set or its answers file whose File is neither a PDF nor a reveal deck), and exiting 2 on an unattempted set with no block in any extract, or an answers file that solves one with no block in any solutions file (extract it; a set counted by an empty or unread Key cell gets that cell fixed first). Every agent that must not see answers reads the extracts and never opens `_build/solutions/`. | SKILL, w02, w05, w07, w08, w09, w11, t:briefs, extract_check.py | I3.C18, I3.G9, I2.G10 |

## 03-backbone

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-060 | The backbone fixes every section number, title and link id before writers start, so parallel writers link to the same names. | w03, S12 | A1.C8, H1.C11 |
| FB-061 | A coverage matrix maps every extract block to a subsection or to an explicit skip, and a script checks it, reading a sub-part in any of its forms (`Q3aii`, `Q3a.ii`). | w03, coverage_check.py | B4 (section 5a), J1.G4 |
| FB-062 | Find figures by a sweep, section by section: every mechanism whose parts pass data, construction whose count or shape matters, comparison of two structures and trace of a drilled procedure, with the slides' diagrams as candidates, not a quota. Keep or cut each with a reason, mark each section `Diagram-taught` (a `yes` section keeps a figure and leads with it, which `coverage_check.py` checks), and show the shortlist and the cut rows to the student before building; in the unattended build, log both in STATUS as a judgment call, and the student's adds and cuts go in by a later `10-polish` figure pass. | w03, w06, w10, t:backbone, coverage_check.py | A1.C12, A1.C13, F.O, J1.C12, I1.C19, I1.C21, I1.C22, I3.C5, F1.C4 |
| FB-063 | Map each subsection to the practice questions that drill it, and each practice question to its section. | w03, S9 | B4 (S9), A1.C19 |
| FB-064 | Weight depth by how the exam tests: procedures get depth, definitional material stays brief. | w03, S33 | B4.C3, F1.C12, D1.C5, D1.C21, E1.C14, E1.C20, E1.C29 |
| FB-065 | Conventions the answers depend on are stated once, in one canonical place, and linked from every use. | w03, S8 | B4 (S8), B4 (hard rules) |

## 04-write

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-070 | STYLE rules 1 to 13 (pedagogy, structure, numbering, Conclusion lines, causation, no redundancy, worked examples, conventions, how it's tested, citations, figures, clickable cross-references, the look). | S1-S13 | B4 (section 5b), A1.C5, A1.C6, A1.C23, A1.C31 |
| FB-071 | Teaching examples use fresh numbers, and the notes' wording never tracks an official solution's: a section reviewer checks it against the answer files its sections draw on. The real answer key lives in its own quarantined file. | S7, w04, w05, t:briefs | A4.C7, I3.C20 |
| FB-072 | Define every symbol and acronym at first use. Gloss logic symbols and unusual notation in plain words where they appear. | S15 | A3.C14, B3.C11, B3.C25, A1.C28 |
| FB-073 | No exam-writer jargon in student-facing text. | S16 | B3.C12, B4.C27 |
| FB-074 | Never coin labels for examples (T1, Tree A). Name an example by its source page or its shape. | S17 | B3.C32, B4.C11 |
| FB-075 | Concise, never compressed: cut the words, never a step, a condition or the tiny instance that shows it. A proof goes step by step on a small instance. | S18 | B3.C13, B3.C14, B4.C19, I1.C10, I3.C3, J1.C4, I2.C13, I2.C14, I2.C15, I1.C24 |
| FB-076 | Open a concept with how it compares to the one it replaces: what is the same, what differs, why it exists. | S19 | B3.C15, B4.C21 |
| FB-077 | Mark slide-only derivations that no practice question asks for as background, with that evidence. | S20, w04 | B3.C16 |
| FB-078 | Every section ends with a "Must know" checklist: one line per point, each linked into the notes, as many points as the exam needs (twelve was fine). | S21, w04 | B3.C7, B3.C9, B4.C29 |
| FB-079 | When the exam asks for proofs, add a proof-techniques block to the notes and the cheat sheet. | S22, w07 | B3.C20, B4.C26 |
| FB-080 | A pitfall states its exact conditions. | S23 | B4.C25, B3.C22 |
| FB-081 | Explain every step of a bound or derivation that a reader would ask "why" about, in plain words. | S24 | B4.C20, B4.C22 |
| FB-082 | Use the course's own terms, and list the aliases the course uses. | S25 | A1.C26, A3.C9 |
| FB-083 | In a construction or counter-example, label each object's role (the real input, the trusted component, the thing under test). | S26 | A1.C22 |
| FB-084 | Each mechanism's section says what it provides and what it does not. | S27 | A3.C15 |
| FB-085 | A conditional claim ("needs X only if Y") shows both the normal case and the edge case. | S28 | A1.C30 |
| FB-086 | No compressed aphorisms: give the concrete situation (who holds what, which channel is trusted). | S29 | A1.C29 |
| FB-087 | When a later section qualifies a number, put a forward caveat where the plain number first appears. | S30 | A1.C25 |
| FB-088 | Confusable pairs get an explicit comparison table. | S31 | B3.C23 |
| FB-089 | Where the slides' convention and the answer keys' convention differ, reconcile them in one place. | S32, w04, w03, w00 | B3.C24, B4.G17, E1.C7 |
| FB-090 | Writers never compute a trace or a number by hand: they leave a TODO-VERIFY marker, and the value comes from the checker. | w04, w05 | B1 (stage 04), B4 (hard rules), B1.G8 |
| FB-091 | After all sections exist, a wiring pass adds the cross-reference links, the lettering and the Conclusion lines. | w04 | A1.C6 |
| FB-092 | When the student reads in a plain-text tool, write for it: no LaTeX, pipe tables, cross-references as text. | S10, w04 | A4.C3, A1.G14 |
| FB-093 | Ship one combined file next to the per-topic files when the student studies from one document. | w04 | A1.C9 |
| FB-094 | Each subsection but the Must-know list opens with a concise box: a few labelled bullets (Rule, Why, Steps, Example, Trap, Answer form, only those that apply), every symbol defined in it, and the full explanation after it, which the box never replaces. The Review view shows every box. | S34, S18, C6, w04, w10, t:convert, t:briefs, verify_page.mjs | I1.C10, I3.C3, J1.C4, I2.C13, I2.C14, I2.C15, I1.C24 |
| FB-095 | The student's text carries no writer leftovers: the build refuses tool-call markup, a feedback-log id in parentheses and a CHASSIS id right after `CHASSIS`, and only warns on a bare STYLE, lesson, backlog or CHASSIS id, `rule (C3)` among them, since a course writes a state (S1), a lecture (L3) or the product rule (C3) the same way, and a rebuild never fails on course text (FB-015). | S16, w04, assemble.py | J1 (section 2) |

## 05-verify

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-100 | The checker reproduces every official solution before anything else uses it. | w05, t:checker | B1 (stage 02), B4 (hard rules) |
| FB-101 | Every worked example and every mock answer runs through the checker. Hand-made values were wrong seven times in one run. | w05 | B4 (stage 08), B1.G8 |
| FB-102 | One reviewer per section, checking in rank order: accuracy, coverage, direction and causation, then STYLE. Findings ranked blocker, major, minor. | w05, t:briefs | B1 (stage 05) |
| FB-103 | A cold solver works the mock without the key. | w05, t:briefs | B1 (stage 05) |
| FB-104 | Audit the diagram slides that no verified trace covers against their extracts. | w05 | B1.C7, B1.C8 |
| FB-105 | Fresh reviewers audit every condensation (checklist, cram order, cheat sheet) against the sources. Reviewers never open `practice/`. | w05 | B3.C8, B4.C29 |
| FB-106 | When a correction lands, fix every copy: notes, checklist, pitfall box, sheet. | w05, w10 | B3.C22 |
| FB-107 | When official solutions arrive, diff every answer against the notes and the solved key, and record the verdict. | w05 | A3.C17 |
| FB-108 | Check a reviewer's claim with the checker before applying it. Fixes are applied single-threaded. | w05 | B1 (stage 05) |
| FB-109 | A cold reader, who sees only the section, flags every undefined term, compressed sentence and untabled confusable pair before publish. | w05, t:briefs, t:plan | D1.C6, D1.C7, D1.C8, D1.C9, D1.C10, D1.C11, D1.C12, D1.C13, D1.C15, D1.C31, E1.C22, E1.C23, E1.C24, E1.C25, E1.C26, E1.C30, F1.C9, F1.C11, F1.C13 |
| FB-191 | Before publish, and before each republish after a change to the notes or a sheet (an `07` sheet, an `08` change, a `09` patch, a `10` pass, an `11` source added), the main session checks the notes and the sheets against every unattempted question set's text (`mock_leak.py --hub .`, which reads every page under `notes/` and the files directly in `cheatsheet/`, a finished exam's archive `cheatsheet/<exam-slug>/` skipped, and builds its own file list from the extracts and solutions files, plus the rendered text of a set or its answers file whose File is neither a PDF nor a reveal deck, read beside its extract, exiting 2 on an unattempted set, or an answers file that solves one, with nothing extracted, until it is extracted; `11`'s unverified path, which can't extract, refuses such a doc and sends it to "A source added"), passing when there is none: a shared run of 8 words or 3 numbers is a blocker, rewritten with fresh numbers and setup (S7). The unattempted sets are the question sets whose own row's Answers cell lacks `attempted` (`no, attempted YYYY-MM-DD` or `yes, attempted YYYY-MM-DD`); a separate answers file's row stays `yes`, since it may solve several sets. A passage the student may want back goes to `_build/held.md` and returns as a patch once the set is attempted and the check on the passage alone (`--pages _build/held-check.md`) passes. | w05, w07, w08, w09, w10, w11, w00, t:hub, t:manifest, mock_leak.py | D1.C26, D1.C28, D1 (section 2), E1 (section 4), F1 (section 2) |

## 06-site

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-110 | One long page with a sticky sidebar and scroll-spy, clickable cross-references and rich inline emphasis. Publish as a private artifact first. | w06, CHASSIS | A1.C13 |
| FB-111 | Generous vertical space, one accent hue per section, a highlight band on bold terms with each section's own dark-mode band (every section checked in both schemes), and a wide borderless sidebar with strong ink that grows on wide screens. | CHASSIS, S13, assemble.py | A1.C15, A1.C16, B4 (S13), J1.C11, I3.C9 |
| FB-112 | Defaults: MathJax tex-svg, the full figure shortlist, light interactivity, a study palette of its own. | CHASSIS, w06 | A1.C14, A4.C5 |
| FB-113 | An exam-day map at the top maps each practice question to section anchors, with a read-first line. | w06, t:chassis | A1.C19 |
| FB-114 | Deploying to the student's own site waits for an explicit go after review. | w06 | A1.C17, A4.C1 |
| FB-115 | Diagram first: every mechanism whose parts pass data, construction whose count or shape matters and comparison of two structures gets a drawn figure, every axis and part labelled, and a diagram-taught section leads with its figure. Every tree or graph example gets an SVG figure, never ASCII. A slide's cropped image only for a reference picture too costly to redraw, cited in its caption. Delete prose that only re-describes a figure. | w06, S11, w04, w10, t:convert | B3.C17, B3.C18, B3.C19, B4.C24, B4.C28, F.O, J1.C12, I1.C19, I1.C21, I1.C22, I3.C5, F1.C4 |
| FB-116 | Worked examples are collapsible and closed by default. | S7, CHASSIS | A2.C5, A2.C6 |
| FB-117 | Step-throughs are fed by the checker's JSON, never hand-typed. | w06, verify_page.mjs | B4 (hard rules), E1.G10, D1.G8 |
| FB-118 | Publish every artifact private, and check the sharing setting after publishing. STATUS records each artifact's owner account and sharing state beside its URL. A URL that can't be updated gets a new private artifact, its link first in the hand-off, and the old URL stays in STATUS marked stale. | w06, w08, w11, t:watch | B4.C16, I3.C6, I2.C29, I2.C32, I2.G1, I2.G2, I3.G5 |
| FB-119 | A screenshot bug report comes from the student's real browser: reproduce it with that platform's scrollbars, not only headless. | w06 | A1.C33 |
| FB-120 | Conversion agents use only the chassis's classes. CSS changes are made by the main session and checked against the chassis screenshots. | S13, w06 | H1.C11, B4 (S13) |
| FB-121 | Material found out of scope stays, under a visible "Not on Exam N" banner. | w06, w11 | A3.C17, B4.C14, A4.C9 |
| FB-122 | Publish from the session that builds the page: a republish elsewhere must first read the whole live copy. | w06 | B3.G3, B4.G13 |
| FB-123 | Every source citation links to its row in the page's source key, which says what the source is, who made it and its file; the build fails on a code with no row, and a code matches its row in any case, the key keeping the row's spelling. | w01, w06, w11, assemble.py, linkcheck.py, verify_page.mjs, t:convert, t:chassis, t:manifest | E1.C10, E1.C11, D1.C20, I3.C8 |
| FB-124 | The theme chrome follows CHASSIS C2 to C4 on the notes page and the mock page (themed scrollbars with an opaque page track, a fixed theme icon, full screen where the frame grants it, the F and T keys), and is judged inside a light-scheme parent frame, never standalone. | C2, C3, C4, t:chassis, t:mock, verify_page.mjs | I3.C9, I3.G10, I2.C32, J1.C5, J1.C6, J1.C7, J1.C9, J1.C10, J1.G6 |
| FB-125 | A link to a figure pins a copy of it in a floating panel (a bottom sheet on a phone) that stays while the student reads on, with a hover preview on desktop. | C5, t:chassis, verify_page.mjs | F.O, J1.C12, I1.C19, I1.C21, I1.C22, I3.C5, F1.C4 |

## 07-cheatsheet

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-130 | Build one only when the exam rules allow it; quote the rule. | w07 | A4 (section 4), H1 (section 5) |
| FB-131 | Ask the font floor, print color and engine once per student. A floor is a floor: the body is the largest size that fits above it. | w07, w00 | B2.C2, B2.C2a |
| FB-132 | Never print the student's name or id. Leave a write-in box tall enough to write in, and remind them when the exam requires it. | w07, t:cheatsheet | B2.C3, B2.C4, B4.C9 |
| FB-133 | When a mock exists, make two sheets. The mock sheet holds nothing derived from the mock, leaves the freed space blank, and is the one published. The final sheet adds the mock-derived items after the attempt. | w07, w08 | B2.C6, B2.C6a, B3.C5, B3.C6, B4.C10 |
| FB-134 | The sheet is self-contained: no pointers into the notes. Grep it for "notes" and section signs before shipping. | w07 | B3.C30, B4.C12 |
| FB-135 | Every item must help cold. Every number on the sheet states its purpose first. | w07 | B3.C27, B3.C33 |
| FB-136 | Scan for gaps twice: by content (agents per deck range), then by question type, adding pros and cons, examples and answer templates. | w07 | B2.C1, B2.C5 |
| FB-137 | Show the draft before changing a printed artifact. Near a full page, new wording is no longer than what it replaces. | w07 | B3.C29, B3.G7 |
| FB-138 | Check overflow and fill per page, not only the page count: a clipped column still prints as two pages. | w07, check_pdf.py | B2.G1, B4.G10, B3.G7 |
| FB-139 | Baseline layout: landscape Letter, 0.2 in margins, five columns, a hue per topic, red only for traps, green and red pros and cons, decision lines, a symbol legend. | t:cheatsheet | B2 (stage 07), B4 (section 5a) |
| FB-140 | Space freed by a scope cut is reserved for the mock-derived items. Check other sections first, then ask. | w07 | B3.C4, B3.C5 |
| FB-141 | Organize the sheet by task. The sheet carries its own index (FB-144), so the cram order needs no map of it. | w07 | B3.C28, I.O, I1.C21, I1.C22, I1.C23, I3.C5 |
| FB-142 | Text inside embedded SVG stays above the font floor. | w07, check_pdf.py | B3.C31, B4.G9 |
| FB-143 | When the exam allows no sheet, offer the notes page's Review view instead: a Review / Full notes toggle over the notes themselves, showing the Must-know lists, the concise boxes, the exam-day map and the worked examples and pitfalls the notes tag for it, copying nothing; its length in minutes of reading, asked at intake, and changed only when nothing is left to untag, which the build enforces. The lists and boxes show untagged and count first: when they alone pass the minutes, the build sets the measured minutes as a STATUS judgment call the student confirms at the cram night's opening, and a session with the student present asks for new ones. | w07, w00, w06, w08, w09, w10, w11, SKILL, t:plan, t:chassis, t:convert, t:briefs, t:fidelity, assemble.py, verify_page.mjs | E1.C17, E1.C18, E1.C21, F1.C3, F1.C5, F1.C8 |
| FB-144 | Side 1 ends with an index: one line per topic block, its side and column, checked against where each block printed and corrected after every move. A tutor answer about a fact says where it sits on the sheet the student will bring. | w07, w09 | I.O, I1.C21, I1.C22, I1.C23, I3.C5 |
| FB-145 | A figure pass over the sheet's outline: a block whose text leaves a direction, a shape or the entries a formula uses to work out cold gets a figure from the notes or the checker, which replaces the text when it says all of it. Every axis on every figure is labelled. | w07 | I.O, I1.C21, I1.C22, I1.C23, I3.C5 |
| FB-146 | A prune list closes the sheet: each block with the question type it serves, or `none found`. The student cuts what they wouldn't use (asked on the cram night when the build ran it), and the room freed goes to the final sheet's items first. | w07, w08 | I.O, I1.C21, I1.C22, I1.C23, I3.C5 |

## 08-practice

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-150 | Mocks cover every question of the source the exam copies. | w08 | A2.C1 |
| FB-151 | For true/false, enumerate the adjacent-variant surface (swap the property, the pair, the direction, the number). Write a verdict and a witness for every variant when the set is small. | w08 | A2.C2, A2.C3, B4.C6 |
| FB-152 | A rule stated for one question type applies to every sibling type before the plan goes out. | w08 | A2.C3 |
| FB-153 | The mock page has three views (by paper, by question type, by topic). Tag each part once and regroup the same items. | w08, t:mock | A2.C4, H1.C11 |
| FB-154 | The key lives in a separate file under a STOP header. The page build never reads it, and a leak check runs on the built page. | w08, mock_leak.py | B4.C7, B4 (section 5a), E1.G7 |
| FB-155 | Clones at exam difficulty with fresh numbers, plus one harder set flagged as harder than the exam. | w08 | A2.C1 |
| FB-156 | A script asserts every key value. | w08 | B1 (stage 05), B4 (section 5a) |
| FB-157 | The night before, offer a cram order: a reading list ranked by points per minute, in tiers with minute budgets, a skip list and an "out of time" fallback to the Must-know lists, pointing into the verified notes rather than new text. | w08 | B3.C1, B3.C2, B3.C10, B4.C15 |
| FB-158 | The cram night opens with the notes page's link and each mock's, defines a tier in one line, starts from what the student has already read, and names the one sheet to print in plain words, never by a label like mock sheet or final sheet. The cram order's Tonight section is the exam-morning card: when, where, what to bring, what is banned and the sheet, each from the hub's Exam facts or marked not recorded. | w08, w00, w07, t:cram-order, t:hub | E1.C5, E1.C6, D1.C22, I1.C1, I1.C29, I3.C24 |
| FB-159 | The cram night offers an Ed re-pull first, and new staff answers go through the source-added path; before each attempt, when the key checker fails, a leak check hits a leak part, or a source came in or a `Reference changed:` line was logged after the mock's last key check, one writer in its own worktree opens each untaken mock's key, fixes the parts the answer touches, reruns the key checker and reports part ids only, so no answer reaches the student's chat. A staff post that states only the exam's format is no source added: it updates the Exam facts and the cram order's pacing, and the notes are swept for a shape or pacing claim it makes stale, with no key recheck. | w08, w09, w10, w11, t:briefs, t:hub, t:verify-mock-key | D1.C23, E1.C15, E1.C19, E1 (section 2), I3.C11 |
| FB-193 | Each cram row names its needs, the earlier subsections it relies on, and a `Read already` line lists what the student has read. A need that no earlier row reads and that line doesn't list becomes a row before it, or the row starts at it; `cram_check.py` refuses it otherwise. | w08, t:cram-order, cram_check.py | J.O, I1.C15, I1.C18 |
| FB-194 | When intake's question asks for one, a watch list: a page of explainer videos per idea of the course, best first, with a notes row where no video is good, made by rankers (who search, then judge from the captions and frames the main session fetches), a merge, cut-loss reviewers and annotators under `templates/WATCH.md`'s rules, built by `videos.py` and checked like any page; run alone, it waits while a `Build running` line stands (a build's or a polish pass's); a reopen archives it with the finished exam. | t:watch, w08, w00, w11, SKILL, t:plan, t:briefs, videos.py, verify_videos.mjs | I.O, I1.C5, I1.C6, I1.C7, I1.C9, I1.C13, I1.C14, I1.C15, I1.C16, I1.C17, I1.C18, I1.C25, I1.C26, I3.C2, I3.C3, I1.G4, I1.G5, I1.G6, I1.G7, I3.G7 |
| FB-195 | A declined mock gets one line of pushback; said again, it stands and STATUS logs it. It stays untaken for every rule (its key closed, the leak checks run with it), the mock sheet becomes the exam sheet, and the final sheet's items go on only once the student hears which parts they would spoil. | w08, w07 | I1.C2, I3.C1 |

## 09-tutor

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-160 | One part at a time. Point to the section of the published page by its number and title, linked (never a source file or a line number), including where each symbol is defined. Let the student attempt. Hints, not the key. Advance only when the student says so. | w09 | A1.C20, A3.C1, A3.C2, A3.C3, A3.C13, I1 (section 2) |
| FB-161 | Grade the verdict and the reasoning separately against rubric points. Say what a full-mark reason contains. Grade the arithmetic and the wording even when the verdict is right. | w09 | A1.C21, A3.C4, A3.C6, A3.C20, A3.C22 |
| FB-162 | To check partial work, verify every intermediate value and list the steps left. | w09 | A3.C5 |
| FB-163 | Give solutions when asked, after one line of pushback. Support a reset: treat the student as not having seen them. | w09 | A3.C7, A3.C8 |
| FB-164 | A small fact question gets a direct answer, short by default: bold-labelled bullets (Rule, Why, Steps, Example, Trap, Answer form), only those it needs, the example a tiny sanity case; the full derivation only when asked. Each symbol is defined at its first use in the answer, and a letter with two meanings in the course is named apart every time. Answer text is exam-ready. | w09 | A3.C12, D1.C30, E1.C28, J1.C4, I1.C10, I1.C24, I1.C25, I1.C27, I1.C28, I2.C13, I2.C14, I3.C3 |
| FB-165 | Quiz mode: one true/false at a time, the full statement with no hint, compared against the key, flagging right-for-the-wrong-reason, with a score per set. | w09 | A3.C18 |
| FB-166 | When a confusion exposes a gap, log it at once as a `proposed` patch line, one short sentence at that point; every five questions, and before the session ends or a mock starts, offer the proposed lines as one notes patch, then republish and bump the version. A good tutor answer goes into the notes, and a one-line form into the sheet if it fits. | w09, w10 | A3.C15, A3.C16, B3.C14, A1.C23, I1 (section 2) |
| FB-167 | During study Q&A the main session only answers. Every edit goes to a dispatched writer with the exact text and the verify steps. | w09 | B3.C34, B4.C13 |
| FB-168 | On pushback, re-derive and concede an overstatement plainly. | w09 | A3.C21 |
| FB-169 | Show a clearer draft first and apply it when the student says so. | w09 | B3.C29 |
| FB-192 | In chat, write symbols as Unicode or plain text, never LaTeX delimiters or HTML tags, and never coin a label the course doesn't use. | w09 | D1.C14, D1.C16, D1.C17, J1.C4, I1.C10, I1.C24, I1.C25, I1.C27, I1.C28, I2.C13, I2.C14, I3.C3 |

## 10-polish

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-170 | Every polish pass is scan, report, then apply on approval, with findings in tiers (exam blockers first). Apply exactly the approved scope and disclose anything beyond it. | w10 | A1.C12, A1.C18, A1.C24, A1.C31, A1.C32, A2.C5, A2.C6 |
| FB-171 | Redundancy audit: count how often each idea is stated, keep the cross-references, and collapse worked examples before cutting content. | w10 | A2.C5, A2.C6 |
| FB-172 | Numbering pass: inventory the existing schemes before adding labels, then standardize (numbered steps for recipes, letters for sets). | w10, S3 | A1.C18, A4.C6 |
| FB-173 | Causation pass: attack or cause first, the property that answers it second, with one standing "how to read every claim" callout. | w10, S5 | A1.C31 |
| FB-174 | Clarity pass: one fresh reader per section, briefed with the failure pattern to look for. | w10 | A1.C23, A1 (stage 10) |

## 11-next-exam

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-180 | When the scope changes after the build, mark the sections "Not on Exam N" and re-trim the sheets, the cram order and what the mocks count in the same pass. | w10, w11 | B4.C14, B3.C3 |
| FB-181 | Don't copy schedule data into the hub: point to its single home. | w11 | B4.C18 |
| FB-182 | At each reopen, ask for the finished exam as graded and read it once into a shape file: each question's type, points and minutes, and where points were lost, knowledge or time, never a question's text. It feeds the depth, the mocks' minute budgets and the cram order's lead, each logged as a modelling choice from one exam; the tutor log's Patterns reach the writers labelled one-exam evidence, never an exam-format claim. | w11, t:briefs | I3.C13, I3.C17, I3.C26, I2.C26, I2.C27, I3.C14, I3.C15, I3.C16 |

## 12-retro

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-190 | Record the exam outcome and which deliverables paid off. Neither past run recorded it. | w12 | B3 (summary), B4 (section 5d) |
