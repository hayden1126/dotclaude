# 04 Write

Baseline as of 2026-10-20; changes only via `12-retro`.

Writing turns the extracts into the topic notes, `notes/NN-<slug>.md`, one file per backbone
section. The notes are the source of truth: the page, the cheat sheet and the mock all derive from
them. Writers work in parallel because the backbone already fixed every section number, title and
link id (FB-054); a wiring pass then joins the files single-threaded (FB-091).

## Step 1: Check the inputs

- `_build/backbone.md` is committed and `coverage_check.py` reports 0 unmapped.
- `_build/verify/examples.out.md` holds the data and traces of every worked example the backbone
  lists (`03-backbone`, step 7). When PLAN.md's Checker line says nothing in the course is
  computable there is no such file: writers build the examples from their cited sources, and
  `05-verify`'s reviewers check every value against them.
- `_build/STYLE.md`, the hub's copy of the skill's `templates/STYLE.md`, exists. Writers follow
  all of it; S14 to S32 are the wording rules a cold reader needs (FB-030, FB-072 to FB-089).

## Step 2: Plan the writers

One writer per backbone section file: with the ids fixed, writing fans out by topic (FB-054). A
course of two or three short sections may be written by the main session alone. For each
writer, list in STATUS before spawning: its file, its backbone section, the extract blocks the
coverage matrix maps into it, and the `examples.out.md` parts it uses.

## Step 3: Spawn one wave

Load the delegation skill first (FB-003). Fill one brief per writer from
`<skill>/templates/agent-briefs.md`, section "Write", and spawn them all at once, unnamed (L45),
each writing its own new file. The brief's Format section holds the Markdown forms `06-site`'s
converter reads (headings, steps, lettered sets, worked examples, How it's tested, Pitfall and FIG
lines). What every writer is held to, beyond STYLE:

- **The backbone is fixed.** Headings, numbers, titles and ids are the backbone's, verbatim: one
  heading per registry row, carrying its id (`## 3.2 <title> {#sec-3-<slug>}` under the file's
  `# §3 <title>`). A link to a section another writer owns uses that section's backbone id; it
  resolves once both files exist.
- **No number by hand** (FB-090). A trace, a computed value or a table of results comes from
  `examples.out.md`. When a value isn't there, the writer writes `TODO-VERIFY: <what to compute,
  from which inputs>` and moves on; `05-verify` fills it from the checker. With no checker there
  is nothing to mark: every value comes from a cited source, and a step that derives one shows its
  working for `05-verify`'s reviewers.
- **Fresh numbers** (FB-071). Worked examples use the checker's data (with no checker, an instance
  built from the sources), never a homework's or a recitation's numbers.
- **Answers.** The notes quote an answer only from a set MANIFEST marks `yes, attempted`. A set
  the student hasn't attempted (`Answers: yes`) is read for its conventions (S32), never quoted,
  and the mock's key never appears: it lives in `practice/`, quarantined.
- **Tested versus background.** Depth follows the backbone's `concise` or `full` mark and its "How
  it's tested" lines. A slide-only derivation no practice question asks for is marked as
  background, with that evidence (FB-077).
- **Each section ends with its Must-know checklist** (FB-078), `sec-N-must-know`, every point a
  link into the section (in plain-text notes, step 6, a pointer naming the subsection).

## Step 4: Check what came back

The main session runs these, since delegated agents can't run scripts (L07):

1. Every planned file exists and holds every heading its backbone section lists.
2. `grep -n TODO-VERIFY notes/*.md`: copy the list into STATUS for `05-verify`.
3. `grep -nE '\b(T[0-9]+|Tree [A-Z])\b' notes/*.md` for coined example labels (S17). Check each
   hit against `_build/extract/`: a label the course's own sources use (T1 for a transaction in a
   database course) is the course's term and stays (S25); rename only labels the notes invented.
4. `grep -n "$(printf '\342\200\224')" notes/*.md` for em dashes (S10): fix every hit.
5. A missing or thin section goes back to its writer (SendMessage to its id) with what is missing.

## Step 5: The wiring pass

After every file exists, the main session alone makes one pass over all of them (FB-091):

- **Links.** Every recall ("Recall from §4"), forward pointer ("used again in §7.3") and the
  backbone's "Cross-section links writers should use" becomes a link that names its target (S12).
- **Lettering.** The section the backbone names lettered each set, its writer adding an anchor
  per member (`{#set-<name>-a}`, S3). Check that no other section letters it again and that every
  other mention links to the member.
- **Conclusion lines** close every construction and worked example (S4).
- **One reconciliation.** Where the slides' convention and the answer keys' convention differ, the
  subsection the backbone's Conventions block names says which one the answers follow, and every
  other use links there (FB-089, S8, S32).

Then run `python3 -I <skill>/scripts/linkcheck.py` from `<root>` until it exits 0 (plain-text
notes are checked by hand instead, step 6). It fails on a
broken link, a registry id no note defines, an id defined twice and a bare `§N.M` reference to a
numbered section. Its warnings need a decision, not silence: an id outside the registry is added to
the backbone or removed, and a bare reference to an unnumbered section is checked by eye.

## Step 6: Reading in a plain-text tool

When `PLAN.md` says the student reads the notes in a plain-text tool (pasting into a document
editor, say) rather than on the page, write for that tool (FB-092): no LaTeX (plain Unicode math),
pipe tables, no `{#id}` anchors, and cross-references as text ("§4.2 <its title>"). `linkcheck.py`
doesn't apply there: the wiring pass checks by eye that every `§N.M` reference names a section the
backbone numbers. When the student studies from one document, also ship `notes/combined.md`, every
section file in order (FB-093).

## Done when

Every backbone section has its file; `linkcheck.py` exits 0 (or, for a plain-text tool, every
reference was checked); the `TODO-VERIFY` list is in STATUS; the notes are committed.
