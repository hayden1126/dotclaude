# CHASSIS: how the notes page looks

Baseline as of 2026-11-12; changes only via `12-retro`.

The look only: layout, palette, components and how the page behaves. What the notes say is
`STYLE.md`'s, and how Markdown becomes HTML is `CONVERT.md`'s. A hub keeps a copy in
`_build/CHASSIS.md`, and the chassis itself in `_build/chassis.html`, copied from the skill's
`templates/notes-chassis.html` with its placeholders filled. `11-next-exam` reconciles both with
the skill's.

## The page

- **One long page** (FB-110): a sticky left rail lists every section and subsection and marks the
  one in view (scroll-spy), with one reading column beside it. Below 900 px the rail becomes a
  drawer behind a "Sections" button, which casts its shadow only while open (closed, just
  off-screen, it would paint a strip down the page's left edge; `verify_page.mjs` fails a closed
  drawer with a shadow). Every cross-reference is a link; bold terms carry a
  highlight band.
- **Space and color** (FB-111): generous vertical space; each section owns one accent hue, on its
  heading, its subsection ticks, its source citations and its bold highlight. `assemble.py`
  writes one accent rule per section, cycling seven hues, and each section's dark rules set its
  own dark highlight (the hue's dark accent at 26% where its table gives none), since the light
  band all but vanishes on the dark background. The rail is wide and borderless, with
  strong ink, and grows on screens of 1500 px and more.
- **Defaults** (FB-112): MathJax `tex-svg`, the full figure shortlist, light interactivity, and
  the chassis's own calm study palette, light with a true dark counterpart (the reader's system
  setting, or the theme icon: C3).
- **The exam-day map** (FB-113), first in the page: a `details.examnav` mapping each practice
  question shape to its section, with a read-first line and a drill-hardest line. `06-site`, step
  4, writes it, with no cram block and no `open` attribute: `assemble.py` refuses either. When
  `practice/cram-order.md` exists, `assemble.py` renders the cram block from it on every build (K02)
  and opens the map: a `div.ecram` at the start of `.ebody`, one `.eq` per tier (its `.eqh` the
  tier's name and minutes), one row per reading row (the one thing in `<b>`, the `§N.K Title` as an
  `a.xref` to `#id`, the depth label in parentheses), then the Skip and Out of time lines in an
  `.edrill`. Mock lines and `## Tonight` stay out. With no file (before `08-practice` step 7), there is no
  cram block and the map stays closed.
- **Worked examples** are collapsible and closed by default (FB-116).
- **The Review view**, when PLAN.md's `- Review view: <N> minutes of reading` line keeps it: a
  Review / Full notes toggle in the top bar (and in the rail, where there is no top bar). Full
  notes is the default; the choice is remembered per viewer in `localStorage`. The Review view
  is a filter over the notes' own blocks, no copy: it shows each section's heading, each `rv`
  block (a worked example, rendered open, or a Pitfall: CONVERT.md's `.rv`), each concise box
  (`.concise`, untagged: every one shows), each `h3` whose subsection holds either, each Must-know `h3` (`id` ending `-must-know`) with the first list after
  it, the exam-day map and the source key, and hides the rest; one fixed line under the lede says
  what the view is. A section whose `Not on <exam>` or `Unverified` banner (`.callout.warn`) comes
  before its first `h3` (a section cut whole, or an unverified section, which ends with its own
  Must-know list) is left out whole, its Must-know list and rail entries included, and
  `assemble.py` refuses an `rv` block in it; a banner further down hides only itself. Once the map has a cram block, sections and their rail entries take the order
  of each section's first row in it (CSS `order`; subsections keep theirs, and sections it names
  no row for follow in page order). A link to anything the view hides switches to Full notes, then
  jumps (a link to a figure pins the figure instead and stays in the view: C5), and so does a load of the page at such a target's hash, or a hash change to one, with the
  Review view remembered. With `- Review view: none: <why>` or no line, `assemble.py` strips the toggle (the
  chassis's `<!-- REVIEW TOGGLE -->` blocks) and refuses any class `rv`.
- **The Review view's budget**: `assemble.py` counts the view's words, the map's included and the
  source key's and the map's cram block left out (the cram block is a reading list into the notes,
  not review text, so a page tagged up to its minutes still builds once `08-practice` step 7
  writes the cram order), and fails the build when they take more than PLAN.md's minutes at
  **150 words a minute** (`READING_RATE`), printing both numbers. The rate is an unmeasured
  estimate for dense study notes, not a measured one. In math, each run of letters and each
  number counts as a word (`\frac{n(n+1)}{2}` is four); code counts like prose, a word per
  blank-separated token; a figure's SVG text doesn't count.

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
| `p.connects` | a "How it's tested", "Connects to" or "Depth" line |
| `a.slink`, `a.xref` | a source citation, linked by assemble.py to its row in the source key, and a cross-reference |
| `.tbl-wrap` | a table's scroll box |
| `figure`, `figcaption`, `.fig-controls` | a figure, its caption and a step-through's buttons; the page's script wraps each figure's SVG in a `figbox` scroll box; a slide-image figure's `img` scales to the column |
| `.concise` | the concise box that opens a subsection: one list of bold-labelled bullets (CONVERT.md; its look is C6) |
| `.bx`, `.accbx`, `.fill-surf`, `.dash`, `.mono`, `.mut`, `.sm`, `.acc` | SVG shapes and text inside a figure; in a table cell, `.mut` and `.sm` make a muted small line (the source key's file name) |
| `details.examnav`, `.ebody`, `.efound`, `.egrid`, `.eq`, `.eqh`, `.edrill` | the exam-day map |
| `.ecram` | the map's cram block, which only `assemble.py` writes (refused in `examnav.html`) |
| `.rv` | a worked example or a Pitfall in the Review view, directly inside its section (CONVERT.md) |

**A step-through** (`06-site`, step 2) is a `<figure id="<fig-id>">` holding its SVG, its
`figcaption`, a `.fig-controls` row of buttons and a status line with `aria-live="polite"`, which
names each frame. The buttons carry `data-act`: `prev` and `next`, plus one per mode when the
figure compares runs (`data-act="ucs"`, with `aria-pressed`), which resets it to its first frame.
The figure shows its first frame as written; `next` is disabled at the last frame and `prev` at
the first. Its handler, in `_build/frag/step-figs.js`, registers as
`window.NotesFig['<fig-id>']`, and the page calls it with the `data-act` of the button pressed.
Only a step-through may add unstyled hook classes for its handler, each named `fs-*`
(`fs-status`). `templates/stepthrough-example/` holds one: the figure, its handler and its
`steps.json`.

## Rules that keep it working

- MathJax 3 `tex-svg` from cdnjs, with `svg: {fontCache: 'none'}`: KaTeX's fonts are blocked by
  the artifact host, and a global font cache garbles glyphs when the host re-renders (L10, L11).
  Its `loader` loads `ui/safe` (MathJax's own filter on the links, classes, ids and styles its
  macros add) and pins `paths.mathjax` to the directory of its script (unpinned, an element named
  `currentScript` on the page chooses the host its components load from); `verify_page.mjs`
  fails a page without either.
- Inline math is `inline-block` with its scrollbar hidden; display math keeps its scrollbar.
  Headless checks hide a stray scrollbar, so the student's screenshot outranks them (L12,
  FB-119).
- Grid tracks are `minmax(0,1fr)` and a `pre` scrolls in its own box, so nothing widens the page
  on a phone (L13).
- No math inside SVG text or headings (L14); a label the rail or a cross-reference shows is typed
  text, never a CSS counter (L16); figures stay inside their section (L17).
- Scroll-spy is a scroll handler, and a check waits for scrolling to settle (L18). At the page's
  bottom it marks the last section active: a short one (the source key) never reaches its line.
  So that rule never overrides a subsection sitting at the line, the script gives the column room
  at its foot (`--tail`, refitted as the column or viewport resizes) until the last shown
  subsection can scroll to the line short of the bottom.
- **C1.** The rail keeps its active link visible by scrolling the rail alone, never
  `scrollIntoView`: that moves the page too and cancels a smooth jump in flight in WebKit
  (L25). `verify_page.mjs` checks the long jump, in WebKit too when it is installed, and in
  both views when the page has the toggle; the Review view keeps the same rail code.
- **C2.** Scrollbars follow the theme: a `--scroll-thumb` token in every theme block, the page's
  own scrollbar `scrollbar-color: var(--scroll-thumb) var(--bg)` with an opaque track (and the
  root's background set), the rail's with a transparent one. `color-scheme` alone isn't enough:
  inside a host frame the native bars stayed light after the toggle, and Chrome inside a
  light-scheme parent frame (claude.ai) paints white behind a transparent page track. So theme
  chrome is judged inside a light-scheme parent iframe, never standalone, where both bugs hide (L26).
  `verify_page.mjs` fails a page whose root track isn't an opaque color, in both themes.
- **C3.** The theme toggle is an icon with no words: an inline SVG half-circle (the ◐ glyph
  renders tiny where the font lacks it) with an `aria-label`, `title="Toggle theme (T)"` and
  `aria-keyshortcuts="t"`. On desktop it is a 40 px button fixed top right (`.themefab`), and
  the reading column keeps a right gutter (`padding-right: 4rem` above 900 px) so no text runs
  under it; at 900 px and below it hides, and the top bar's own icon takes over. No theme button
  sits in the rail. `verify_page.mjs` fails a theme button with words or in the rail, and a
  page with no theme icon fixed on screen at 1280 px.
- **C4.** Full screen shows only where the frame grants it: its buttons (stacked under the theme
  icon on desktop, `.fsfab`; in the top bar on phones, `.fsbtn`) start `hidden` and show when
  `document.fullscreenEnabled` (or WebKit's) is true. They toggle full screen on the root
  element and keep `aria-pressed` in step on `fullscreenchange`. At 480 px and below, a top bar
  with the Review toggle has no room for it, as for the brand. Keys: F toggles full screen
  (where granted) and T the theme, both ignored while Ctrl, Cmd or Alt is held (so Ctrl+F still
  finds) and while focus is in an input, textarea, select or contenteditable.
  `verify_page.mjs` fails full-screen buttons hidden where it is granted or shown where not, a
  T that doesn't flip the theme, and a T that flips it with Ctrl held or typed in an input.
  C2 to C4 (FB-124) hold on the mock page too (`templates/mock-page.html`, its view bar standing in for
  the top bar), so the two pages read as one set, and `verify_page.mjs` checks them there.
- **C5.** A link to a figure pins a copy of it (FB-125). A plain click on an `a.xref` whose target is a
  `figure` opens a clone of that one figure (no second copy in the HTML) in a floating panel,
  `.figpanel`, fixed bottom right on desktop and a bottom sheet at 900 px and below (at most 45%
  of the viewport's height, scrolling inside itself, the page's foot padded so its last lines can
  scroll above it). The panel stays while the student reads on; another figure link swaps its
  figure; its close button, Escape and "Go to figure" (a plain jump to the original) end it. It is
  a non-modal `role="dialog"` whose `aria-label` names the figure (its caption's "Fig N.K", else
  its image's label); focus moves to it on open and back to the link on close, and the page keeps
  its own scroll. Every id in the clone takes a suffix (`--pin`), each reference to one
  (`url(#...)`, `#...`, an ARIA id list) rewritten, so no id repeats and an arrow marker still
  draws. The clone's SVG or image scales to the panel's width, its viewBox kept (the page's 460 px
  floor for a figure on a phone doesn't apply inside the panel); the Review view's hiding class comes off the clone, so a figure link pins in that view too
  without leaving it. A step-through pins as its current frame, static: its `.fig-controls` are
  dropped and its status line keeps its text but not `aria-live`. The clone takes its section's
  accent and follows the theme. Ctrl, Cmd, Shift, Alt or a middle click keeps the plain jump. On a
  desktop with a mouse (`(hover:hover) and (pointer:fine)`, wider than 900 px), resting on a figure
  link for 300 ms shows the same clone as an `aria-hidden` preview, `.figpeek`, beside the link;
  leaving the link hides it, and a click turns it into the pinned panel. No preview on touch.
  `verify_page.mjs` checks it at 390 and 1280 px in each scheme and view: the click opens the
  panel without moving the page, focus inside, its label naming the figure, the copy's drawing
  inside the panel's width, no id repeated, a
  step-through's copy without controls, the panel on screen after a scroll (a bottom sheet at most
  46% high at 390 px, under half the width at 1280 px), its background the theme's surface, a
  second figure link swapping it, Escape closing it with focus back on the link, the close button
  closing it, a Ctrl+click left to the browser, and at 1280 px a hover preview after 300 ms that
  holds no repeated id and goes on leaving, while a touch never shows one.
- **C6.** A concise box (FB-094) is a `div.concise` holding one `ul`, each item opening with its label in
  `strong`; the box takes its section's accent as a top border and a faint wash, both themes from
  the tokens. Above 560 px the labels hang in a column of their own (small capitals in the
  section's accent, no highlight band) so the eye runs down them; at 560 px and below they sit
  inline before their text. It sits right under its `h3` (after the Depth line, when there is
  one), so the box is what a skim reads first, and the Review view shows every box with its `h3`.
  `verify_page.mjs` fails a Review view that hides one.
- The page is a fragment (title, font links, style, body content, scripts), as past runs
  published it: the artifact host wraps it in a standards-mode document, and `verify_page.mjs`
  wraps it the same way before checking it, since loaded alone it renders in quirks mode (L19).

## Changing the look

Converters add content only, in the chassis's classes: no inline styles and no new CSS (FB-120,
S13). A CSS change is the main session's, made in `_build/chassis.html`, and checked against the
reference screenshots in `<skill>/templates/chassis-shots/` (1280 px light and 390 px dark: the top
of the page, four subsections, a step-through at its last frame, each static figure, an open worked
example, the open exam-day map, a figure pinned (`-pin`), and the source key with a row targeted, the rail marking it active, together every
component; and, for a page with the toggle, the same set in the Review view, each named with
`-review` after its width and scheme, such as `390-dark-review-top.png`) before it ships. A look change worth keeping for later courses goes to `12-retro`, which
regenerates the shots from the skill repo's synthetic sample hub, `tests/exam_prep/fixtures/site/`:
assemble it, then run `verify_page.mjs` on it with
`--spy sec-1-sums,sec-1-rules,sec-2-basics,sec-2-walks --steps _build/frag/steps.json`.
