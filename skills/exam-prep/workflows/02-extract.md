# 02 Extract

Baseline as of 2026-11-12; changes only via `12-retro`.

Extraction turns every in-scope page into verbatim text and data, organized by source unit (a deck,
a homework), never by topic: the topic order comes in `03-backbone` (FB-050). Its output,
`_build/extract/<name>.md`, is the only copy of the course content every later stage reads, so it
transcribes and never summarizes.

## Step 1: Plan the wave

- **One whole deck per agent** (FB-053). A deck of more than about 45 pages splits at section
  dividers into parts of at most about 45 pages; each later part's agent also reads the previous
  part's last three pages, as context only. A slide is never split between agents (FB-041).
- **Small documents share an agent:** a homework or recitation with its official solutions (the
  brief's SOLUTIONS slots). That agent writes both files of the pair, the extract and the
  solutions file, each solution keyed by its question part's block id (below, "The solutions
  file").
- **By source type:** a PDF agent reads `_build/text/` and `_build/pages/`; a Word document's agent
  reads `_build/text/<doc>.md` and `_build/media/<doc>/`. A reveal deck agent reads a slice that
  the main session cuts before spawning:
  `python3 -I <skill>/scripts/reveal_slice.py slice <deck> --from H --to H --base <deck url> -o
  _build/slices/<name>.html`. Its headers carry the fragments, and with `--base` the full URL, an
  extract cites.
- `reserved` rows get no agent, and every brief names them as never to be opened (FB-023).
- Write the agent list (doc, pages, context pages, output file) into STATUS before spawning: it
  is where a resumed session picks up.

## Step 2: Spawn one wave

Load the delegation skill first (FB-003). Fill one brief per agent from
`<skill>/templates/agent-briefs.md`, section "Extract", and spawn them all at once, unnamed (L45),
each writing its own file. Budget about three tool calls a page (the text, the image, the
write) plus ten; a budget too low truncates the extract. Fan out wide here: extraction carries no
cross-references. Stages that do (the writers' links) work from the backbone's fixed id registry
(FB-054).

While the wave runs, the main session starts the checker (`05-verify`, step 1) from the first
solutions file, once its agent reports done and the `UNREADABLE:` flags of its pair are resolved
(step 3.2 for those files): the checker needs only those (a course's instances arrive with
them), and it must reproduce them before anything uses it (FB-100).

## The solutions file

An extract holds no answer (FB-056). The extract agent of a doc with official solutions writes a
second file, `_build/solutions/<name>.md`, under its extract's `<name>`; no other agent writes
either (hard rule 6). Both are tracked in the hub. The solutions file opens with
`# <DOC> solutions (extract)` and the extract's `Sources:` line, and ends with the same
`Coverage:` closing line as an extract, covering the answers pages. Between them:

- one block per question part of a solved doc, `### [HW1 Q1a]` (a title is optional), the part's
  own block id from the extract, holding either `Solution [HW1S p.2]: ...` and its working
  (tables, fenced traces) or the exact line `No official solution.`;
- the page or section block of each answers page: every block of a separate answers file
  (`### [HW1S p.1] ...`), and each key page of a past exam that its MANIFEST row names (below).

`UNREADABLE:` flags and `(illegible at 300 dpi: ...)` work in it as in an extract.

The solved docs come from MANIFEST's in-scope rows (Scope `in` or `concepts only`): an Answers
`yes` doc with a `solutions to <doc>` note solves the docs it names (`solutions to HW1, HW2 and
HW3` names three, each a MANIFEST doc id), and one with no note solves itself (a past exam with
its key), so a separate answers file needs the note. A `reserved`, `pending` or `out` answers
file solves nothing. A past exam with its key names its key pages in its Notes (`01-ingest`,
step 3): `key p.N`, `key pp. N-M` or a list (`key pp. 7-9, 11`), or `key inline` when each
solution sits under its question on the same page, so no page is a key page. The brief's `{{KEY
PAGES}}` slot gives the agent those pages, copied from the note, or `none` for `key inline`.
Only the named key pages go to the solutions file; every other page of that doc (the cover, the
rules, a formula sheet, an appendix table) keeps its block in the extract, so the answer-blind
agents (the mock writer cloning a question's setup, the gap scan) still read it. A part's
solution goes under its part's block in the solutions file wherever it sits, on a key page or
under its question. A part's block counts as answered only with a
`Solution [<doc> <loc>]` line, the cite followed by a colon or the line's end, or the exact line
`No official solution.`
`python3 -I <skill>/scripts/extract_check.py --parts` prints the number of question parts whose
solutions block holds a `Solution [` line: `05-verify`'s PARTS, never a lecture's worked example.

Who reads it. Hard rule 4 and FB-191 keep the answers of a set the student hasn't attempted out
of everything they read, so the agents that must not see answers read `_build/extract/` and never
open or search `_build/solutions/`, whether or not the student has attempted the set: the sheet
gap scan, the audits (Must-know, cheat sheet, cram order) and the mock writer (`agent-briefs.md`
says so in each brief and keeps each one's searches off that folder). The cold reader and the
cold solver open nothing under `_build/`. The extract agents, the section writers and section
reviewers, the checker and the tutor read both folders: they need a set's conventions, and the
briefs keep them from quoting its answers.

## Step 3: Check what came back

The main session runs every check: delegated agents can't run Python or `pdfinfo`, so a check an
agent says it ran didn't run (L07). First `git status`: it names nothing but the extracts and
the solutions files (an agent that wrote anywhere else broke its brief: undo that and say so in
STATUS).

1. `python3 -I <skill>/scripts/extract_check.py`. It checks every in-scope MANIFEST row against
   the blocks of both folders, `_build/extract/` and `_build/solutions/`: each in-scope page of a
   PDF rendered and with a block, each in-scope slide of a deck, at least one block for any other
   source (the Ed digest is read as it is). It prints the missing pages or slides and the
   image-only and `UNREADABLE:` counts per document, then each open `UNREADABLE:` flag in either
   folder by file and line, with the re-read it needs (step 2). It fails while any such flag is
   open; each value marked `(illegible at 300 dpi: <what>)` (step 2) is listed by file and line,
   `<file>:<line>: (illegible at 300 dpi: ...), counted, not a failure`. A missing
   page goes back to its agent (SendMessage to its id), or the main session extracts it. Blocks
   for a `reserved` doc fail the check: delete them, and find which brief let the agent open it
   (FB-023). Blocks for a `pending` row fail too: its file has arrived, so give the row a real
   Scope (`01-ingest`, step 5). A Scope cell the check can't read fails rather than being
   guessed at. A warning about an unknown doc id is usually a typo in a header: fix the header.

   It checks the pairing of the two folders ("The solutions file") and fails each of these,
   printed `<file>:<line>: <TAG>`:
   - `NO SOLUTION BLOCK`: a question part (`Q..`, not a stem) of a solved doc has a block in an
     extract and none in any solutions file. The agent that wrote the pair, or the main session,
     adds it, as the line says:
     `NO SOLUTION BLOCK: write its solution or "No official solution." under ### [<doc> <part>] in _build/solutions/<name>.md`;
   - `NO SUCH PART`: a solutions block names a part no extract has;
   - `TWO SOLUTIONS BLOCKS`: a part has two blocks across the solutions files;
   - `EMPTY SOLUTIONS BLOCK`: a part's block holds neither a `Solution [` line nor
     `No official solution.`;
   - `SOLUTION IN AN EXTRACT`: a bracketed `Solution [<doc> <loc>]` or bold `**Solution:**` line
     in a block of a solved doc;
   - `CITES AN ANSWERS PAGE`: an extract's line citing an answers page (a `Pages:` line holding
     only cites, and the closing `Coverage:` line, aside);
   - `AN ANSWERS PAGE IN AN EXTRACT: ... move it to _build/solutions/<name>.md`: a page block of
     an answers doc on an answers page: any page of a separate answers file, or a key page its
     MANIFEST row names.

   `SOLUTION IN AN EXTRACT` holds for any extract block, a lecture's too, when its `Solution [`
   or `**Solution...**` line cites a solved or answers doc; and the lines above a file's first
   `###` header get every check a block's lines get. A solution line moves into its solutions
   file, under the part it answers, and so does an answers page's block. `CITES AN ANSWERS PAGE`
   has two fixes: a line that gives an answer moves into the solutions file, under its part; a
   line that is the question's own text keeps its place and cites the question's own page
   instead. It also fails, by doc and with no file or line:
   - `<doc>: ANSWERS WITH NO PAIRING`: an in-scope Answers `yes` doc with no question parts in
     any extract and no `solutions to` note. Add the note to its MANIFEST row.
   - `<doc>: NO KEY NOTE: a doc with its own key names its key pages in Notes ("key pp. N-M", or "key inline")`:
     an in-scope self-answering row (Answers `yes`, no `solutions to` note) without its key
     note. Look at the PDF and add the note (`01-ingest`, step 3); a page the note now names moves
     to the solutions file.
   - `<doc>: NOTE NAMES NO DOC: ...`: a `solutions to` note names an id that is no MANIFEST doc
     id. Fix the note or the id.

   It warns on a solutions block for a stem (each of its parts still needs its own block), on a
   loose `Solution:` line outside a fence in a solved doc's extract block, and on an `Answer:`,
   `Ans:` or `Final answer:` line (or the like) in a solved doc's extract block that isn't an
   answer blank. The main session reads each: an answer or a solution moves to the solutions
   file, under its part, and question text stays. With no MANIFEST.md, `extract_check.py
   --parts` exits 2, as the full check does.
2. Resolve every `UNREADABLE:` flag and every flagged small label at 300 dpi, on a crop: a whole
   300 dpi page gets scaled down by the image viewer, which loses the gain. Find the label on the
   100 dpi image, multiply its box by 3, and crop into `_build/pages/<doc>@300dpi/` (make it
   first): `pdftoppm -r 300 -f N -l N -x X -y Y -W W -H H -png -singlefile <file>
   _build/pages/<doc>@300dpi/crop-NNN`. (`RENDER_DPI=300 bash <skill>/scripts/render_pdf.sh
   <file> <doc> N N` renders the whole page there when a crop isn't enough.) Replace the flag
   with the value and `(re-read at 300 dpi)`. A misread edge weight carries into every trace
   built on it (FB-055, L06). A value still illegible at 300 dpi, on the crop and on the whole
   page, is never guessed: replace its flag with `(illegible at 300 dpi: <what, and where on the
   page>)`, note it in STATUS as a judgment call, and ask the student for it once no `Build
   running` line stands (hard rule 1). Only the main session writes that form, after the re-read.
   Once the student gives the value, the main session replaces the mark with it, noting
   `(given by the student)`; if the checker exists, it turns the self-test's `skip` for that part
   (`05-verify` step 1, which names the mark) back into a `check` of the value. It then reruns
   `extract_check.py` and the self-test (`python3 -I _build/verify/selftest.py`), since a value
   in a solutions file may be one the self-test reproduces.
3. Spot-check one diagram per deck against its page image, and check that the page numbers in the
   headers are real pages, never numbers from an agent's summary (FB-051).

## Step 4: Record coverage

STATUS gets, per document: pages in range, pages with a block, image-only pages with the reason, and
UNREADABLE flags resolved (the check's output saved to `_build/logs/extract_check.txt`). It also
says which diagrams a checker trace will verify and which only reviewers will see; `05-verify`
audits the second group against their images (FB-052, FB-104).

## Done when

`extract_check.py` exits 0 (it fails while any `UNREADABLE:` flag is open in either folder,
though not on a value marked `(illegible at 300 dpi: ...)`, while a question part of a solved doc
has no solutions block or a part has two, while a solutions block names no extract's part or
holds neither a `Solution [` line nor `No official solution.`, while an extract holds a solution
line, a line citing an answers page or a block of an answers page, while an in-scope Answers
`yes` doc with no question parts lacks its `solutions to` note or one with its own key lacks its
key note, or while a `solutions to` note names no MANIFEST doc), and STATUS has the coverage and
each value marked illegible as a judgment call. Its warnings (a solutions block for a stem, a
loose `Solution:` line or an `Answer:` line in a solved doc's extract) are each read and either
fixed or noted in STATUS. It
skips a doc on a STATUS `Unverified:` line (`11-next-exam`, "A source added unverified") until
that doc has a block. Commit the extracts and the solutions files: they are tracked in the hub,
which stays local.
