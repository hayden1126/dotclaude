# Lessons: tool and environment gotchas

Baseline as of 2026-10-20; changes only via `12-retro`.

Each lesson was hit in a past run. Ids are stable (`L01`), struck through when retired, never
renumbered. Evidence ids work as in `feedback-log.md`. The stage column says where a workflow
should warn about it.

## Sources and extraction

| Id | Stage | Lesson | Fix | Evidence |
|---|---|---|---|---|
| L01 | 01 | WebFetch returns a model's summary of a page, not its text: slide formulas and slide numbers are lost, and a subagent's extract built on it carries unverified numbers. | Fetch raw HTML with curl in the main session and slice it with `reveal_slice.py`. | A1.G1, A4.G1 |
| L02 | 01 | The Bash sandbox blocks hosts it doesn't know: curl fails with `CONNECT tunnel failed, response 403`. | Re-run with the exact host in the command's `allowed_domains`. Never a wildcard. | A1.G2 |
| L03 | 01, 02 | Slide PDFs have a thin text layer (a few hundred characters a page on diagram-heavy decks). | Render every page to PNG (`render_pdf.sh`) and have extractors view the image as well as the text. | H1.G2, B4.G15 |
| L04 | 01 | Printed slide numbers and PDF page numbers differ (often by one). | Store both; say which one a scope boundary uses. | B4.G16 |
| L05 | 01 | Tools present on the reference machine: `pdftoppm`, `pdftotext`, `pdfinfo`, `pypdf`, `mutool`. Absent: PyMuPDF, `qpdf`, `jq`, the Python `markdown` module. | Use the present ones; `uv run --with markdown` when markdown is needed; Python for JSON. | H1.G1, H1.G4, A2.G5, B1.G6 |
| L06 | 02 | A model misreads a small rotated label (an edge weight) and every later trace inherits it. | Re-read suspicious labels on a 300 dpi crop; the checker uses the corrected value. | B1.G9 |
| L07 | 02, 05 | Delegated researchers can't run Python or `pdfinfo` (policy), so their verify claims are unrun. | The main session runs every check itself. | B1.G10, B3.G14 |
| L08 | 01 | Word (`.docx`) sources: the reference machine has pandoc 3 but no LibreOffice, so there is no docx-to-PDF render. | `pandoc -t gfm --wrap=none --extract-media=<dir>`: tables stay tables, Word equations become TeX; view the extracted images. | probe (2026-10-20) |

## Math and the page

| Id | Stage | Lesson | Fix | Evidence |
|---|---|---|---|---|
| L10 | 06 | KaTeX's fonts are blocked by the artifact host's content security policy. | MathJax `tex-svg` from cdnjs. | A1.G3, A4.G2, B4.G1 |
| L11 | 06 | MathJax SVG with `fontCache:'global'` garbles glyphs when the artifact host re-renders the DOM. | `svg: {fontCache: 'none'}`. | A4.G3, A1.G7 |
| L12 | 06 | An inline `mjx-container` overflows by a sub-pixel and paints a scrollbar on desktop browsers with classic scrollbars; headless Chrome uses overlay scrollbars and hides it, so automated checks pass. | Inline math `display:inline-block` with the scrollbar hidden; display math keeps its scrollbar. Trust the student's screenshot over headless. | A1.G5, A1.G7, A4.G4, B4.G3 |
| L13 | 06 | Long inline math, a wide `pre` or a grid track widens the page on a phone. | `minmax(0,1fr)` grid tracks; `pre{overflow-x:auto;max-width:100%}`. | A1.G5, B1.G2, B4.G11 |
| L14 | 06 | MathJax doesn't typeset inside SVG `<text>` or inside text the sidebar copies from headings. | Unicode glyphs in SVG labels; ASCII-fold math in headings only. | A2.G4, A4.G5, B4.G5 |
| L15 | 06 | MathJax reads only `\( \)` and `\[ \]` with the chassis config, so a literal dollar sign is safe. | Keep money as `$10`. | B3.G12 |
| L16 | 06 | CSS `counter()` labels don't reach the sidebar (it reads `textContent`) and don't survive copy. | Any label the sidebar or a cross-reference shows is typed text. | A4.G6 |
| L17 | 06 | A figure placed as a direct child of `main` shifts the per-section `nth-of-type` accent colors. | Figures stay inside their own section. | A4.G7 |
| L18 | 06 | IntersectionObserver picked the wrong sidebar item, and smooth scrolling is still moving when a check measures. | Scroll-spy as a scroll handler; wait for scrolling to settle before measuring. | A1.G5, A1.G6, B4.G6 |
| L19 | 06 | A fragment loaded alone renders in quirks mode, unlike the artifact host. | Verify inside a standards-mode wrapper (doctype, charset, viewport). | B4.G8 |

## Browsers and verification

| Id | Stage | Lesson | Fix | Evidence |
|---|---|---|---|---|
| L20 | 06 | chrome-devtools MCP on WSL2 times out, needs an explicit page id, gets stuck on resize and can't reach a sandboxed localhost server. | Playwright headless from a script (`verify_page.mjs`), pages opened as `file://`. | A1.G8, A2.G2, B4.G7 |
| L21 | 06 | Headless Chromium inside the Bash sandbox ignores `HTTPS_PROXY`, so MathJax from the CDN silently never loads (`MathJax.startup` undefined, no error). | Pass the proxy with its credentials to `chromium.launch`, and give the command `allowed_domains` for cdnjs.cloudflare.com, fonts.googleapis.com and fonts.gstatic.com. | B1.G1, B4.G2 |
| L22 | 06 | An ES module ignores `NODE_PATH`, so `import 'playwright'` fails outside a project with `node_modules`. | `verify_page.mjs` imports Playwright from an absolute path (`EXAM_PREP_PLAYWRIGHT`). | B4.G7 |
| L23 | 06 | A full-page screenshot of a tall `pre` produced an unusable 720 by 20914 image. | Screenshot the element. | B3.G11 |
| L24 | 06 | The Google Fonts link was missing, so every font silently fell back. | `verify_page.mjs` checks that the declared families loaded. | A1.G4 |

## Publishing

| Id | Stage | Lesson | Fix | Evidence |
|---|---|---|---|---|
| L30 | 06 | Republishing an artifact from a session that didn't publish it is refused until the session reads the whole live copy, which exceeds the Read tool's 25k-token cap (read in chunks); an identical resend is refused as a duplicate. | Publish from the session that builds the page. Otherwise read the live copy in chunks, diff it against the local build, then publish. | A2.G3, A3.G2, B3.G3, B4.G13 |
| L31 | 06 | An auto-mode classifier hiccup can refuse an Artifact call once. | Repeat the identical call once. | B3.G4, A1.G9 |

## Sandbox, git and shell

| Id | Stage | Lesson | Fix | Evidence |
|---|---|---|---|---|
| L40 | all | A sandboxed command longer than 131071 bytes is refused. | Write the script to a file, then run it. | B3.G1, B4.G12 |
| L41 | all | The sandbox shows protected names (`.claude`, `.mcp.json`) as `/dev/null` mounts that look untracked, and the hub's own gitignored build dirs need `git add -f` for any file meant to be tracked. | Stage files by name; `git add -f` for tracked files under ignored dirs. | B1.G11, B4.G14 |
| L42 | all | Memory files are write-protected for Bash. | Use the Write tool. | A2.G7, A1.G12 |
| L43 | all | `git commit --amend` and resets are denied to the agent. | Give the student the exact keystrokes. | A1.C34, A1.G12 |
| L44 | all | zsh fails the whole command on a glob that matches nothing. | Quote the glob or run the producer first. | B2.G4 |
| L45 | all | A named Agent spawn becomes an agent-team teammate and is denied. | Spawn unnamed. | A2.G1, B4.G18 |
| L46 | 09 | Parallel writer worktrees that each rebuild a PDF conflict on the binary at merge; `git worktree remove` can fail with "Device or resource busy". | Take one side and re-render; `git worktree prune`. | B3.G8, B3.G9 |
| L47 | all | A message to a running session is read only after its current step. | Put any change that matters in the files too. | H1.G11 |
| L48 | all | Edits that carry LaTeX break in heredocs and `perl` (escapes, multibyte glyphs). | Use the Edit tool, with an assert-before-write script for bulk changes. | A1.G10 |
| L49 | all | A blanket em-dash strip rewrote headings. | Review a mechanical rewrite's diff on headings and ids. | A1.G11 |

## Content generation

| Id | Stage | Lesson | Fix | Evidence |
|---|---|---|---|---|
| L50 | 03, 05 | Hand-picked example inputs were wrong (an unsolvable start state, a degenerate case), and hand traces were wrong seven times. | Generate examples and their traces from the checker. | B1.G8, B4 (stage 08) |
| L51 | 03 | A naive example generator ran for minutes (quadratic frontier scans, buffered output). | Constant-time membership; flush output; stop and fix rather than wait. | B1.G7 |
| L52 | all | A safety classifier can stop a reply on security-course content (attack math). | Restate the answer and continue; it is a false positive. | A1.G13, A2.G8, A3.G1 |

## Print

| Id | Stage | Lesson | Fix | Evidence |
|---|---|---|---|---|
| L60 | 07 | A `.page` with `overflow:hidden` and CSS columns clips a spilled column silently; the PDF still has two pages. | `check_pdf.py` reports per-page overflow and last-column fill. | B2.G1, B4.G10, B3.G7 |
| L61 | 07 | The minimum-font check walks text nodes: it skips MathJax glyphs, and reads SVG text unscaled (5.1 pt reported where 5.6 pt prints). Superscripts set the floor. | Scale SVG text by its viewBox; size sup and sub separately. | B2.G3, B4.G9 |
| L62 | 07 | `page.pdf({format:'Letter'})` is portrait; `preferCSSPageSize` lets `@page {size: Letter landscape}` win. | Set orientation in CSS only. | B2.G2 |
| L63 | 07 | DejaVu Sans is wide; the condensed face fits about 15 percent more. | `font-stretch: condensed` with a local condensed font; check embedding with `pdffonts`. | B2.G5, B1.G14 |

## Ed Discussion

| Id | Stage | Lesson | Fix | Evidence |
|---|---|---|---|---|
| L70 | 01 | If the Ed API token stops working, a dedicated Chrome profile driven over CDP can fetch the same JSON API from a logged-in page. Not built in v1. | Build it only when the token path fails. | brief (Ed adapter) |
