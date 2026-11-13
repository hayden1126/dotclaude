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
- **Small documents share an agent:** a homework or recitation with an answers file that solves
  it alone (its Key cell `for HW1`), or a past exam holding its own key (the brief's SOLUTIONS
  slots). That agent writes both files of the pair, the extract and the set's solutions file
  `_build/solutions/<name>.md`, under the extract's `<name>`, each solution keyed by its question
  part's block id (below, "The solutions file").
- **An answers file that solves several sets gets its own agent** (its Key cell `for HW1, HW2
  and HW3`). It reads those sets' question pages for their part ids, and the answers file, and
  writes each set's part blocks in that set's solutions file, `_build/solutions/<name>.md` under
  that set's extract `<name>`, plus the answers file's own page or section blocks, held in full
  like any answers page, in its own file, `_build/solutions/<doc id in lower case>.md`
  (`_build/solutions/hws.md` for `HWS`). Each set's own agent then writes only its extract (the
  brief without the SOLUTIONS slots), with the same part ids. An agent may write several files,
  and no file is written by two agents (hard rule 6).
- **A set is extracted before its answers file**, or in the same wave: an answers block's home
  is beside its set's extract ("The solutions file"), and a block whose set has no block in any
  extract has no home (`NO HOME FILE`, step 3).
- **By source type:** a PDF agent reads `_build/text/` and `_build/pages/`; a Word document's agent
  reads `_build/text/<doc>.md` and `_build/media/<doc>/`. A reveal deck agent reads a slice that
  the main session cuts before spawning:
  `python3 -I <skill>/scripts/reveal_slice.py slice <deck> --from H --to H --base <deck url> -o
  _build/slices/<name>.html`. Its headers carry the fragments, and with `--base` the full URL, an
  extract cites.
- `reserved` rows get no agent, and every brief names them as never to be opened (FB-023).
- Write the agent list (doc, pages, context pages, output files) into STATUS before spawning: it
  is where a resumed session picks up.

## Step 2: Spawn one wave

Load the delegation skill first (FB-003). Fill one brief per agent from
`<skill>/templates/agent-briefs.md`, section "Extract", and spawn them all at once, unnamed (L45),
each writing its own files. Budget about three tool calls a page (the text, the image, the
write) plus ten; a budget too low truncates the extract. Fan out wide here: extraction carries no
cross-references. Stages that do (the writers' links) work from the backbone's fixed id registry
(FB-054).

While the wave runs, the main session starts the checker (`05-verify`, step 1) from the first
solutions file, once its agent reports done and the `UNREADABLE:` flags of its pair are resolved
(step 3.2 for those files): the checker needs only those (a course's instances arrive with
them), and it must reproduce them before anything uses it (FB-100).

## The solutions file

An extract holds no answer (FB-056). Official solutions sit in `_build/solutions/`, and every
block there has one home file, by what it is (`_build/extract/hw1.md` pairs with
`_build/solutions/hw1.md`). A set's home is the solutions file beside each extract holding any
block of that set (a page, section or slide block counts, not only a question part's), so a deck
split into parts `r3.md` and `r3b.md` keeps a key slide beside the part holding it, the part
whose range covers that slide:

- a set's part or stem blocks: `_build/solutions/<name>.md`, beside the set's extract `<name>`
  (a part's block beside the extract holding its question block);
- the page or section blocks of an answers file whose Key cell is `for <one doc>`: that set's
  file, beside the one set it solves;
- the page or section blocks of an answers file whose Key cell names several docs:
  `_build/solutions/<doc id in lower case>.md` (`hws.md` for `HWS`), its own file, since it
  solves several sets; it holds those pages in full, as any answers page's block is written;
- a doc holding its own key: its key page or key section blocks sit in the file beside its own
  extract.

`extract_check.py` fails a block anywhere else (`WRONG SOLUTIONS FILE`, step 3). A block whose
home can't be computed, since no extract holds a block of its set (a stem's, a single-set
answers file's page, a key block), has none and fails `NO HOME FILE` (step 3): extract a set
before its answers file. The set's
extract agent writes the set's file, except when the set's answers file solves several sets: that
file's own agent writes each of those sets' files and its own (step 1). No file is written by two
agents (hard rule 6). All are tracked in the hub. Each solutions file opens with `# <DOC>
solutions (extract)`, naming its one set (or, for a multi-set answers file's own file, that
file), never several docs, then the `Sources:` line of its set's extract with the answers file
added, and ends with a `Coverage:` closing line in the extract's form, for the blocks it holds.
Between them:

- one block per question part of the set, `### [HW1 Q1a]` (a title is optional), the part's own
  block id from the extract, holding either `Solution [HW1S p.2]: ...` and its working (tables,
  fenced traces) or the exact line `No official solution.`; a stem block `### [HW1 Q3 stem]` is
  allowed for official text a question's parts share, but each part keeps its own block and its
  own solution;
- the page or section block of each answers page in its home (above): every page of a separate
  answers file (`### [HW1S p.1] ...`), and each key page or key section of a doc holding its own
  key that its Key cell names (below). A multi-set answers file's page blocks hold the page's
  official text in full, its shared setups and tables included, in its own file.

`UNREADABLE:` flags and `(illegible at 300 dpi: ...)` work in it as in an extract. An erratum
(an official answer that is wrong) is the main session's alone: an `Erratum: ...` line under the
part's `Solution [` line, the official line kept (`05-verify` step 1).

The solved docs come from MANIFEST's Key column (`01-ingest` step 3 writes it; Notes are free
text and nothing reads them for this), on in-scope rows (Scope `in` or `concepts only`) whose
Answers is `yes`. A Key cell `for HW1, HW2 and HW3` marks a separate answers file solving the docs
it names, each a MANIFEST doc id and never the row's own. Any other Key form marks a doc holding
its own key (a past exam), which solves itself: `pp. 7-9, 11` or `p.N` names its key pages, on a
PDF only; `inline` names none, since each solution sits under its
question on the same page; `sections: Marking scheme, Answers` names the key sections of a source
without pages (a Word exam, or a slide deck by its slides, `sections: #/5, #/6`) by their exact
locators, and its extract agent writes each one as a block with that locator, `### [PE3 Marking
scheme] ...`. A block whose locator is such a name followed, after any spaces, by nothing, by a
character that is no letter or digit (`### [PE3 Marking scheme (continued)]`, `[PE3 Marking
scheme: Q2]`, `[PE3 #/5/0]` under `sections: #/5`) or by `Q` and a digit (`[PE3 Marking scheme
Q2]`) is key material too, and goes to the solutions file; `Key formulas` under `sections: Key`
is not, and stays in the extract. The rule has one exception: a locator naming a key section is
key material whatever page reference it carries (`[PE3 Marking scheme p.2]` is key). A `reserved`,
`pending` or `out` answers file solves nothing, nor does a row on a STATUS `Unverified:` line
until it is verified. The brief's `{{KEY PAGES}}` slot gives the agent what the Key cell names:
the pages, `none` for `inline`, or the key sections by locator. Only those pages or sections go
to the solutions file; every other page or section of that doc (the cover, the rules, a formula
sheet, an appendix table) keeps its block in the extract, so the answer-blind agents (the mock
writer cloning a question's setup, the gap scan) still read it. A part's solution goes under its
part's block in the set's solutions file wherever it sits, on a key page or under its question.
A part's block counts as answered only with a `Solution [<doc> <loc>]` line, the cite followed by
a colon or the line's end, or the exact line `No official solution.`
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
     extract and none in any solutions file. The agent that wrote the set's solutions file, or the
     main session, adds it, as the line says:
     `NO SOLUTION BLOCK: write its solution or "No official solution." under ### [<doc> <part>] in _build/solutions/<name>.md`;
   - `NO SUCH PART`: a solutions block names a part no extract has;
   - `TWO SOLUTIONS BLOCKS`: a part has two blocks across the solutions files;
   - `WRONG SOLUTIONS FILE: [<doc> <loc>] belongs in _build/solutions/<name>.md, <why>`: a block
     sits in a solutions file other than its home ("The solutions file"), and `<why>` names the
     rule: `beside its extract` (a set's part or stem block), `beside the one set it solves` (a
     page or section block of an answers file whose Key is `for <one doc>`), `its own file, since
     it solves several sets` (one of an answers file whose Key names several docs, its home
     `_build/solutions/<doc id in lower case>.md`) or `beside its own extract` (a key page or key
     section block of a doc holding its own key). Move the block there; the agent that owns that
     file (step 1), or the main session, moves it;
   - `NO HOME FILE: [<doc> <loc>] has no home: no extract holds a block of <SET>; extract <SET> first`:
     a block whose home ("The solutions file") can't be computed, since its set `<SET>` has no
     block in any extract: a stem's block, a page or section block of an answers file whose Key
     is `for <one doc>`, or a key block of a doc holding its own key. Extract a set before its
     answers file: write `<SET>`'s extract (step 1), then rerun the check, which names the
     block's home if it sits elsewhere;
   - `EMPTY SOLUTIONS BLOCK`: a part's block holds neither a `Solution [` line nor
     `No official solution.`;
   - `SOLUTION IN AN EXTRACT`: a bracketed `Solution [<doc> <loc>]` or bold `**Solution:**` line
     in a block of a solved doc;
   - `CITES AN ANSWERS PAGE`: an extract's line citing an answers page (a `Pages:` line holding
     only cites, and the closing `Coverage:` line, aside);
   - `AN ANSWERS PAGE IN AN EXTRACT: [<doc> <loc>] is ...; move it to _build/solutions/<name>.md, <why>`:
     a page block of an answers doc on an answers page, named with its home file and the rule
     that sets it, `<why>` as `WRONG SOLUTIONS FILE` gives it (`beside the one set it solves`,
     `its own file, since it solves several sets`, `beside its own extract`): any page of a
     separate answers file, or a key page or key section its Key cell names (a locator that is a
     key section's name followed, after any spaces, by nothing, a character that is no letter or
     digit, or `Q` and a digit, included);

   `SOLUTION IN AN EXTRACT` holds for any extract block, a lecture's too, when its `Solution [`
   or `**Solution...**` line cites a solved or answers doc; and the lines above a file's first
   `###` header get every check a block's lines get. A solution line moves into its set's
   solutions file, under the part it answers, and so does an answers page's block. `CITES AN
   ANSWERS PAGE` has two fixes: a line that gives an answer moves into the solutions file, under
   its part; a line that is the question's own text keeps its place and cites the question's own
   page instead. It also fails each in-scope MANIFEST row whose Key cell is missing, unread or
   wrong (`01-ingest` step 3 gives the forms; the fix is in the cell, after looking at the file),
   printed by doc with no file or line:
   - `<doc>: NO KEY: an Answers yes row fills its Key cell ("for HW1, HW2", "pp. 7-9, 11", "inline" or "sections: <name>, <name>")`:
     an in-scope Answers `yes` row whose Key cell is empty or `-`. A page the new cell names
     moves to the solutions file.
   - `<doc>: UNREAD KEY: "<cell>" isn't a Key form: write "for HW1, HW2", "pp. 7-9, 11", "inline" or "sections: Marking scheme, Answers"`:
     a Key cell in any other wording. Rewrite it in one of the forms; a remark goes in Notes.
   - `<doc>: KEY NAMES NO DOC: "<word>" in its Key cell is no doc id in MANIFEST.md`: a `for ...`
     cell names an id that is no MANIFEST doc id. Fix the cell or the id.
   - `<doc>: KEY NAMES ITS OWN DOC: "for" names the docs an answers file solves; a doc holding its own key uses "pp. N-M", "inline" or "sections: <name>"`:
     a `for ...` cell names its own row's id. A doc holding its own key takes one of those forms.
   - `<doc>: KEY WITHOUT ANSWERS: its Key cell is filled but Answers isn't yes`: either the file
     holds answers (set Answers to `yes`) or it doesn't (empty the Key cell, or write `-`).
   - `<doc>: SECTIONS KEY ON A PAGED DOC: use "pp. N-M" or "inline"`: `sections: ...` on a doc
     with pages, whose key is named by its pages.
   - `<doc>: PAGES KEY ON AN UNPAGED DOC: use "sections: <name>, <name>" or "inline"`: a `p.` or
     `pp.` key on a row whose File isn't a PDF, whatever its Pages holds. A Word file or a slide deck
     names its key sections or slides by their exact locators: `sections: Marking scheme`,
     `sections: #/5, #/6`.
   - `<doc>: KEY SECTION NOT FOUND: no block [<doc> <name>] in its home solutions file`: a
     section the Key cell names has no block in the doc's home solutions file ("The solutions
     file": the one beside each extract holding a block of the doc; no other solutions file is
     read), neither one with that exact locator nor one of the section (`[<doc> Marking scheme Q1]`, `[<doc> Marking scheme
     (continued)]`, `[<doc> #/5/0]` under `sections: #/5`), by the key-section rule and its one
     exception (a page reference: `[<doc> Marking scheme p.2]` is key). Give the key section's
     block that locator, in the doc's home solutions file, or fix the name in the cell.
   - `<doc>: ANSWERS WITH NO PAIRING: ...`: an in-scope Answers `yes` doc that holds its own key
     by its Key cell, yet has no question block in any extract: its question parts need blocks in
     an extract, as the line says (a separate answers file needs a `for ...` cell instead).

   It warns on a solutions block for a stem while one of its parts lacks a block of its own (a
   stem block holding official text the parts share is allowed once each part has its own), on a
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
has no solutions block or a part has two, while any solutions block sits outside its home file
(`WRONG SOLUTIONS FILE`) or has none (`NO HOME FILE`), while a solutions
block names no extract's part or holds neither a `Solution [` line nor `No official solution.`,
while an extract holds a solution line, a line citing an answers page or a block of an answers
page, and while an in-scope MANIFEST row fails:
`NO KEY`, `UNREAD KEY`, `KEY NAMES NO DOC`, `KEY NAMES ITS OWN DOC`, `KEY WITHOUT ANSWERS`,
`SECTIONS KEY ON A PAGED DOC`, `PAGES KEY ON AN UNPAGED DOC`, `KEY SECTION NOT FOUND` or
`ANSWERS WITH NO PAIRING`), and STATUS has the coverage and each value marked illegible as a
judgment call. Its warnings (a solutions block for a stem, a
loose `Solution:` line or an `Answer:` line in a solved doc's extract) are each read and either
fixed or noted in STATUS. It
skips a doc on a STATUS `Unverified:` line (`11-next-exam`, "A source added unverified") until
that doc has a block. Commit the extracts and the solutions files: they are tracked in the hub,
which stays local.
