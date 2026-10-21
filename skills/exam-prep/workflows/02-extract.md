# 02 Extract

Baseline as of 2026-10-20; changes only via `12-retro`.

Extraction turns every in-scope page into verbatim text and data, organized by source unit (a deck,
a homework), never by topic: the topic order comes in `03-backbone` (FB-050). Its output,
`_build/extract/<name>.md`, is the only copy of the course content every later stage reads, so it
transcribes and never summarizes.

## Step 1: Plan the wave

- **One whole deck per agent** (FB-053). A deck of more than about 45 pages splits at section
  dividers into parts of at most about 45 pages; each later part's agent also reads the previous
  part's last three pages, as context only. A slide is never split between agents (FB-041).
- **Small documents share an agent:** a homework or recitation with its official solutions (the
  brief's SOLUTIONS slots), so each solution lands under its question.
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
extract that holds official solutions, once its agent reports done and that extract's
`UNREADABLE:` flags are resolved (step 3.2 for that file): the checker needs only those (a course's
instances arrive with them), and it must reproduce them before anything uses it (FB-100).

## Step 3: Check what came back

The main session runs every check: delegated agents can't run Python or `pdfinfo`, so a check an
agent says it ran didn't run (L07). First `git status`: it names nothing but the extracts (an
agent that wrote anywhere else broke its brief: undo that and say so in STATUS).

1. `python3 -I <skill>/scripts/extract_check.py`. It checks every in-scope MANIFEST row against
   the blocks: each in-scope page of a PDF rendered and with a block, each in-scope slide of a
   deck, at least one block for any other source (the Ed digest is read as it is). It prints the
   missing pages or slides and the image-only and `UNREADABLE:` counts per document. A missing
   page goes back to its agent (SendMessage to its id), or the main session extracts it. Blocks
   for a `reserved` doc fail the check: delete them, and find which brief let the agent open it
   (FB-023). Blocks for a `pending` row fail too: its file has arrived, so give the row a real
   Scope (`01-ingest`, step 5). A Scope cell the check can't read fails rather than being
   guessed at. A warning about an unknown doc id is usually a typo in a header: fix the header.
2. Resolve every `UNREADABLE:` flag and every flagged small label at 300 dpi, on a crop: a whole
   300 dpi page gets scaled down by the image viewer, which loses the gain. Find the label on the
   100 dpi image, multiply its box by 3, and crop into `_build/pages/<doc>@300dpi/` (make it
   first): `pdftoppm -r 300 -f N -l N -x X -y Y -W W -H H -png -singlefile <file>
   _build/pages/<doc>@300dpi/crop-NNN`. (`RENDER_DPI=300 bash <skill>/scripts/render_pdf.sh
   <file> <doc> N N` renders the whole page there when a crop isn't enough.) Replace the flag
   with the value and `(re-read at 300 dpi)`. A misread edge weight carries into every trace
   built on it (FB-055, L06).
3. Spot-check one diagram per deck against its page image, and check that the page numbers in the
   headers are real pages, never numbers from an agent's summary (FB-051).

## Step 4: Record coverage

STATUS gets, per document: pages in range, pages with a block, image-only pages with the reason, and
UNREADABLE flags resolved (the check's output saved to `_build/logs/extract_check.txt`). It also
says which diagrams a checker trace will verify and which only reviewers will see; `05-verify`
audits the second group against their images (FB-052, FB-104).

## Done when

`extract_check.py` exits 0 (it fails while any `UNREADABLE:` flag is open), and STATUS has the
coverage. Commit the extracts: they are tracked in the hub, which stays local.
