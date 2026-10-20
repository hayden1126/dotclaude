# CHASSIS: how the notes page looks

Baseline as of 2026-10-20; changes only via `12-retro`.

The look only: layout, palette, components and how the page behaves. What the notes say is
`STYLE.md`'s, and how Markdown becomes HTML is `CONVERT.md`'s. A hub keeps a copy in
`_build/CHASSIS.md`, and the chassis itself in `_build/chassis.html`, copied from the skill's
`templates/notes-chassis.html` with its placeholders filled. `11-next-exam` reconciles both with
the skill's.

## The page

- **One long page** (FB-110): a sticky left rail lists every section and subsection and marks the
  one in view (scroll-spy), with one reading column beside it. Below 900 px the rail becomes a
  drawer behind a "Sections" button. Every cross-reference is a link; bold terms carry a
  highlight band.
- **Space and color** (FB-111): generous vertical space; each section owns one accent hue, on its
  heading, its subsection ticks, its source citations and its bold highlight. `assemble.py`
  writes one accent rule per section, cycling seven hues. The rail is wide and borderless, with
  strong ink, and grows on screens of 1500 px and more.
- **Defaults** (FB-112): MathJax `tex-svg`, the full figure shortlist, light interactivity, and
  the chassis's own calm study palette, light with a true dark counterpart (the reader's system
  setting, or the theme button).
- **The exam-day map** (FB-113), first in the page: a closed `details.examnav` mapping each
  practice question shape to its section, with a read-first line and a drill-hardest line.
  `06-site`, step 4, writes it.
- **Worked examples** are collapsible and closed by default (FB-116).

## Components (the class vocabulary)

`CONVERT.md` maps the Markdown onto these; nothing else is styled. `assemble.py` reads this table:
the classes written `.class` in its first column are the only ones a fragment may use.

| Class | What it is |
|---|---|
| `section.note`, `h2 .n` | a section and its § number |
| `ol.steps` | a procedure; the CSS draws each "Step N" badge |
| `.callout`, `.lab` | a callout and its label; a plain one holds background material (S20) |
| `.callout.def`, `.callout.key`, `.callout.warn` | a definition, a key rule, and a pitfall or a "Not on <exam>" banner |
| `details.callout.example.wex`, `.wex-t` | a worked example, closed, and its title |
| `p.connects` | a "How it's tested" or "Connects to" line |
| `a.slink`, `a.xref` | a source citation (no href) and a cross-reference |
| `.tbl-wrap` | a table's scroll box |
| `figure`, `figcaption`, `.fig-controls` | a figure, its caption and a step-through's buttons; the page's script wraps each figure's SVG in a `figbox` scroll box |
| `.bx`, `.accbx`, `.fill-surf`, `.dash`, `.mono`, `.mut`, `.sm`, `.acc` | SVG shapes and text inside a figure |
| `details.examnav`, `.ebody`, `.efound`, `.egrid`, `.eq`, `.eqh`, `.edrill` | the exam-day map |

**A step-through** (`06-site`, step 2) is a `<figure id="<fig-id>">` holding its SVG, its
`figcaption`, a `.fig-controls` row of buttons and a status line with `aria-live="polite"`, which
names each frame. The buttons carry `data-act`: `prev` and `next`, plus one per mode when the
figure compares runs (`data-act="ucs"`, with `aria-pressed`), which resets it to its first frame.
The figure shows its first frame as written; `next` is disabled at the last frame and `prev` at
the first. Its handler, in `_build/frag/step-figs.js`, registers as
`window.NotesFig['<fig-id>']`, and the page calls it with the `data-act` of the button pressed.
Only a step-through may add unstyled hook classes for its handler, each named `fs-*`
(`fs-status`).

## Rules that keep it working

- MathJax 3 `tex-svg` from cdnjs, with `svg: {fontCache: 'none'}`: KaTeX's fonts are blocked by
  the artifact host, and a global font cache garbles glyphs when the host re-renders (L10, L11).
- Inline math is `inline-block` with its scrollbar hidden; display math keeps its scrollbar.
  Headless checks hide a stray scrollbar, so the student's screenshot outranks them (L12,
  FB-119).
- Grid tracks are `minmax(0,1fr)` and a `pre` scrolls in its own box, so nothing widens the page
  on a phone (L13).
- No math inside SVG text or headings (L14); a label the rail or a cross-reference shows is typed
  text, never a CSS counter (L16); figures stay inside their section (L17).
- Scroll-spy is a scroll handler, and a check waits for scrolling to settle (L18).
- The page is a fragment (title, font links, style, body content, scripts), as past runs
  published it: the artifact host wraps it in a standards-mode document, and `verify_page.mjs`
  wraps it the same way before checking it, since loaded alone it renders in quirks mode (L19).

## Changing the look

Converters add content only, in the chassis's classes: no inline styles and no new CSS (FB-120,
S13). A CSS change is the main session's, made in `_build/chassis.html`, and checked against the
reference screenshots in `<skill>/templates/chassis-shots/` (1280 px light and 390 px dark: the
top of the page, four subsections, a step-through at its last frame, an open worked example and
the open exam-day map, together every component) before it ships. A look change worth keeping for later courses goes to
`12-retro`, which regenerates the shots from the skill repo's synthetic sample hub,
`tests/exam_prep/fixtures/site/`: assemble it, then run `verify_page.mjs` on it with
`--spy sec-1-sums,sec-1-rules,sec-2-basics,sec-2-walks --steps _build/frag/steps.json`.
