# Feedback log

Baseline as of 2026-10-20; changes only via `12-retro`.

Every rule the skill encodes came from a correction or a stated preference in a past run. This log
traces each one to its evidence. Ids are stable: a retired rule is struck through and keeps its id,
and a new rule takes the next free number, so a hub doc that cites `FB-073` keeps pointing at the
same rule.

- **Evidence** cites `<source>.<item>`, such as `A1.C23` (source A1, correction 23) or `B3.G7`
  (gotcha 7). The sources are harvest reports of two completed runs (A and B) and the session that
  planned run B (H). They quote the student verbatim, so they stay private and are not shipped. A
  maintainer who has them reads `~/scratch/exam-prep/evidence.md` for the index.
- **Home** is where the rule lives in the skill: a STYLE or CHASSIS rule (`S4`, `C2`), a workflow
  step (`w04`), a template (`t:cheatsheet`) or a script (`linkcheck.py`). `12-retro` keeps this
  column current.
- **Stage** tags use the workflow numbers. `all` means a hard rule in SKILL.md.

## all: cross-cutting

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-001 | After the plan is approved, run unattended. Log judgment calls in the hub's STATUS instead of asking. | SKILL | B1.C1, B4.C5, H1.C4 |
| FB-002 | Make every stage resumable: check what is already on disk and start at the first unfinished stage. All state lives in files. | SKILL | B1.C2, H1.C8 |
| FB-003 | Load the delegation skill before the first spawn. Parallel within a wave, one output file per agent, unnamed spawns, merges single-threaded. | SKILL | B1.C3, B4 (hard rules), A2.G1 |
| FB-004 | Record a ship-priority order at intake (notes site, then cheat sheet, then mock) and cut from the bottom when time runs short. | w00 | B1.C4, B4.C5 |
| FB-005 | End each work block with the handoff skill and a local commit. Never push. Course material stays untracked; the hub's progress files are tracked. | SKILL | A1.C11, A2.C7, B1.C6, B2.C7, B3.C36, A4.C8 |
| FB-006 | Persist every build source into the hub. The session scratchpad does not survive a clear. | SKILL | A1.C11, A4.C2 |
| FB-007 | Keep the planning session and the execution session apart. Everything durable is on disk before the planner stops. | w00 | H1.C9, H1.C14 |
| FB-008 | Before concluding that something does not exist, read the hub's STATUS and PLAN. STATUS lists every published artifact's URL. | SKILL | A3.C19, A3.G6 |
| FB-009 | Put numbered options in the visible message. Never refer to options the student can't see. | SKILL | A1.C10 |
| FB-010 | Start a new course from the latest baseline with every past correction applied up front, not rediscovered as late polish. | SKILL | H1.C2 |
| FB-011 | Course material is copyrighted: `sources/` and rendered pages are gitignored, the hub repo stays local, and no remote is added without the student's go. | SKILL, t:hub | B4.C8, A4.C8 |
| FB-012 | Never state a prediction about the exam without a source. Record the instructor's exam-format statement in the hub and cite it. | w00, w09 | A3.C10 |

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
| FB-030 | Write for a student who may have skipped the lectures: assume no prior exposure. | w04, t:style | A1.C1 |

## 01-ingest

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-040 | Never use WebFetch on slides: it summarizes and drops formulas and slide numbers. Fetch raw HTML with curl and slice it; render PDFs page by page to image and text, and view the image when the text layer is thin. | w01, SKILL | A1.G1, A4.G1, B4.G15, H1.G2 |
| FB-041 | A deck is not a lecture: cut extraction boundaries by content. Never split one slide between two agents. | w01, w02 | A1.C3 |
| FB-042 | Select source files by name. Never glob a downloads folder, which holds unrelated secrets. | w01 | H1.G8 |
| FB-043 | Delete originals only after a SHA-256 match against `sources/`. After that, STATUS says `sources/` is the only copy. | w01 | B1.C8, B2.C8, B4.C17 |
| FB-044 | MANIFEST has one row per document: id, file, pages, in, out or reserved, and a note. Take counts from disk. | w01, t:manifest | B1 (stage 01), B4 (section 5a) |

## 02-extract

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-050 | Extracts are organized by source unit; notes are organized by topic. | w02 | A1.C6 |
| FB-051 | Capture provenance once, at extraction: the base location once per file, the slide or page per fact, and a verbatim anchor phrase for key formulas and tables. | w02, t:briefs | A1.C7 |
| FB-052 | Extractors view every page image as well as the text, write diagrams as data, and flag what they can't read. The run's report states image coverage per deck. | w02, t:briefs | B1.C7, B4 (stage 02) |
| FB-053 | One whole deck per agent. Split a big deck at a section divider with a three-page overlap. | w02 | B4 (stage 02), H1 (stage steps) |
| FB-054 | Fan out wide for raw extraction. A stage that carries cross-references works from a fixed id registry or stays single-threaded. | w02, w04 | A4.C4 |
| FB-055 | Check small, rotated or crowded labels on a higher-resolution crop before using the value. | w02 | B1.G9 |

## 03-backbone

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-060 | The backbone fixes every section number, title and link id before writers start, so parallel writers link to the same names. | w03, S12 | A1.C8, H1.C11 |
| FB-061 | A coverage matrix maps every extract block to a subsection or to an explicit skip, and a script checks it. | w03 | B4 (section 5a) |
| FB-062 | Shortlist figures from both directions: the notes' mechanisms that prose can't carry, and the slides' diagrams. Report the shortlist before building. | w03, w06 | A1.C12, A1.C13 |
| FB-063 | Map each subsection to the practice questions that drill it, and each practice question to its section. | w03, S9 | B4 (S9), A1.C19 |
| FB-064 | Weight depth by how the exam tests: procedures get depth, definitional material stays brief. | w03 | B4.C3 |
| FB-065 | Conventions the answers depend on are stated once, in one canonical place, and linked from every use. | w03, S8 | B4 (S8), B4 (hard rules) |

## 04-write

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-070 | STYLE rules 1 to 13 (pedagogy, structure, numbering, Conclusion lines, causation, no redundancy, worked examples, conventions, how it's tested, citations, figures, clickable cross-references, the look). | S1-S13 | B4 (section 5b), A1.C5, A1.C6, A1.C23, A1.C31 |
| FB-071 | Teaching examples use fresh numbers. The real answer key lives in its own quarantined file. | S7, w04 | A4.C7 |
| FB-072 | Define every symbol and acronym at first use. Gloss logic symbols and unusual notation in plain words where they appear. | w04, t:style | A3.C14, B3.C11, B3.C25, A1.C28 |
| FB-073 | No exam-writer jargon in student-facing text. | w04, t:style | B3.C12, B4.C27 |
| FB-074 | Never coin labels for examples (T1, Tree A). Name an example by its source page or its shape. | w04, t:style | B3.C32, B4.C11 |
| FB-075 | Prefer a three-sentence explanation or a tiny worked instance over a compressed argument. A proof goes step by step on a small instance. | w04, t:style | B3.C13, B3.C14, B4.C19 |
| FB-076 | Open a concept with how it compares to the one it replaces: what is the same, what differs, why it exists. | w04, t:style | B3.C15, B4.C21 |
| FB-077 | Mark slide-only derivations that no practice question asks for as background, with that evidence. | w04 | B3.C16 |
| FB-078 | Every section ends with a "Must know" checklist: one line per point, each linked into the notes, as many points as the exam needs (twelve was fine). | w04, t:style | B3.C7, B3.C9, B4.C29 |
| FB-079 | When the exam asks for proofs, add a proof-techniques block to the notes and the cheat sheet. | w04, w07 | B3.C20, B4.C26 |
| FB-080 | A pitfall states its exact conditions. | w04, t:style | B4.C25, B3.C22 |
| FB-081 | Explain every step of a bound or derivation that a reader would ask "why" about, in plain words. | w04, t:style | B4.C20, B4.C22 |
| FB-082 | Use the course's own terms, and list the aliases the course uses. | w04, t:style | A1.C26, A3.C9 |
| FB-083 | In a construction or counter-example, label each object's role (the real input, the trusted component, the thing under test). | w04, t:style | A1.C22 |
| FB-084 | Each mechanism's section says what it provides and what it does not. | w04, t:style | A3.C15 |
| FB-085 | A conditional claim ("needs X only if Y") shows both the normal case and the edge case. | w04, t:style | A1.C30 |
| FB-086 | No compressed aphorisms: give the concrete situation (who holds what, which channel is trusted). | w04, t:style | A1.C29 |
| FB-087 | When a later section qualifies a number, put a forward caveat where the plain number first appears. | w04, t:style | A1.C25 |
| FB-088 | Confusable pairs get an explicit comparison table. | w04, t:style | B3.C23 |
| FB-089 | Where the slides' convention and the answer keys' convention differ, reconcile them in one place. | w04 | B3.C24, B4.G17 |
| FB-090 | Writers never compute a trace or a number by hand: they leave a TODO-VERIFY marker, and the value comes from the checker. | w04, w05 | B1 (stage 04), B4 (hard rules), B1.G8 |
| FB-091 | After all sections exist, a wiring pass adds the cross-reference links, the lettering and the Conclusion lines. | w04 | A1.C6 |
| FB-092 | When the student reads in a plain-text tool, write for it: no LaTeX, pipe tables, cross-references as text. | w04 | A4.C3, A1.G14 |
| FB-093 | Ship one combined file next to the per-topic files when the student studies from one document. | w04 | A1.C9 |

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

## 06-site

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-110 | One long page with a sticky sidebar and scroll-spy, clickable cross-references and rich inline emphasis. Publish as a private artifact first. | w06, CHASSIS | A1.C13 |
| FB-111 | Generous vertical space, one accent hue per section, a highlight band on bold terms, and a wide borderless sidebar with strong ink that grows on wide screens. | CHASSIS, S13 | A1.C15, A1.C16, B4 (S13) |
| FB-112 | Defaults: MathJax tex-svg, the full figure shortlist, light interactivity, a study palette of its own. | CHASSIS, w06 | A1.C14, A4.C5 |
| FB-113 | An exam-day map at the top maps each practice question to section anchors, with a read-first line. | w06, t:chassis | A1.C19 |
| FB-114 | Deploying to the student's own site waits for an explicit go after review. | w06 | A1.C17, A4.C1 |
| FB-115 | Every tree or graph example gets an SVG figure, never ASCII. Delete prose that only re-describes a figure. | w06, S11 | B3.C17, B3.C18, B3.C19, B4.C24, B4.C28 |
| FB-116 | Worked examples are collapsible and closed by default. | S7, CHASSIS | A2.C5, A2.C6 |
| FB-117 | Step-throughs are fed by the checker's JSON, never hand-typed. | w06 | B4 (hard rules) |
| FB-118 | Publish every artifact private, and check the sharing setting after publishing. | w06 | B4.C16 |
| FB-119 | A screenshot bug report comes from the student's real browser: reproduce it with that platform's scrollbars, not only headless. | w06 | A1.C33 |
| FB-120 | Conversion agents use only the chassis's classes. CSS changes are made by the main session and checked against the chassis screenshots. | S13, w06 | H1.C11, B4 (S13) |
| FB-121 | Material found out of scope stays, under a visible "Not on Exam N" banner. | w06, w11 | A3.C17, B4.C14, A4.C9 |
| FB-122 | Publish from the session that builds the page: a republish elsewhere must first read the whole live copy. | w06 | B3.G3, B4.G13 |

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
| FB-141 | Organize the sheet by task, and give the cram order a map of the sheet. | w07 | B3.C28 |
| FB-142 | Text inside embedded SVG stays above the font floor. | w07, check_pdf.py | B3.C31, B4.G9 |

## 08-practice

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-150 | Mocks cover every question of the source the exam copies. | w08 | A2.C1 |
| FB-151 | For true/false, enumerate the adjacent-variant surface (swap the property, the pair, the direction, the number). Write a verdict and a witness for every variant when the set is small. | w08 | A2.C2, A2.C3, B4.C6 |
| FB-152 | A rule stated for one question type applies to every sibling type before the plan goes out. | w08 | A2.C3 |
| FB-153 | The mock page has three views (by paper, by question type, by topic). Tag each part once and regroup the same items. | w08, t:mock | A2.C4, H1.C11 |
| FB-154 | The key lives in a separate file under a STOP header. The page build never reads it, and a leak check runs on the built page. | w08 | B4.C7, B4 (section 5a) |
| FB-155 | Clones at exam difficulty with fresh numbers, plus one harder set flagged as harder than the exam. | w08 | A2.C1 |
| FB-156 | A script asserts every key value. | w08 | B1 (stage 05), B4 (section 5a) |
| FB-157 | The night before, offer a cram order: a reading list ranked by points per minute, in tiers with minute budgets, a skip list and an "out of time" fallback to the Must-know lists, pointing into the verified notes rather than new text. | w08 | B3.C1, B3.C2, B3.C10, B4.C15 |

## 09-tutor

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-160 | One part at a time. Point to the section of the published page (never a source file), including where each symbol is defined. Let the student attempt. Hints, not the key. Advance only when the student says so. | w09 | A1.C20, A3.C1, A3.C2, A3.C3, A3.C13 |
| FB-161 | Grade the verdict and the reasoning separately against rubric points. Say what a full-mark reason contains. Grade the arithmetic and the wording even when the verdict is right. | w09 | A1.C21, A3.C4, A3.C6, A3.C20, A3.C22 |
| FB-162 | To check partial work, verify every intermediate value and list the steps left. | w09 | A3.C5 |
| FB-163 | Give solutions when asked, after one line of pushback. Support a reset: treat the student as not having seen them. | w09 | A3.C7, A3.C8 |
| FB-164 | A small fact question gets a direct answer and a tiny sanity case. Answer text is short and exam-ready. | w09 | A3.C12 |
| FB-165 | Quiz mode: one true/false at a time, the full statement with no hint, compared against the key, flagging right-for-the-wrong-reason, with a score per set. | w09 | A3.C18 |
| FB-166 | When a confusion exposes a gap, patch the notes at once with one short sentence at that point, republish and bump the version. A good tutor answer goes into the notes, and a one-line form into the sheet if it fits. | w09, w10 | A3.C15, A3.C16, B3.C14, A1.C23 |
| FB-167 | During study Q&A the main session only answers. Every edit goes to a dispatched writer with the exact text and the verify steps. | w09 | B3.C34, B4.C13 |
| FB-168 | On pushback, re-derive and concede an overstatement plainly. | w09 | A3.C21 |
| FB-169 | Show a clearer draft first and apply it when the student says so. | w09 | B3.C29 |

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
| FB-180 | When the scope changes after the build, mark the sections "Not on Exam N" and re-trim the sheets, the cram order and the mock totals in the same pass. | w11 | B4.C14, B3.C3 |
| FB-181 | Don't copy schedule data into the hub: point to its single home. | w11 | B4.C18 |

## 12-retro

| Id | Rule | Home | Evidence |
|---|---|---|---|
| FB-190 | Record the exam outcome and which deliverables paid off. Neither past run recorded it. | w12 | B3 (summary), B4 (section 5d) |
