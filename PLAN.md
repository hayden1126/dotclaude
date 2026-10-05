# PLAN: deck-production geometry gate

> **Status (2026-10-04): built.** `deckkit geometry` (`scripts/geometry.py`, `geometry_probe.js`,
> `geometry.rules.toml`) and `tests/deck_production/` landed on `feat/deck-geometry` over several
> review rounds, and the wiring round connected it to `deckkit regress`, SKILL.md, `deckkit
> doctor`, the `deck.toml` template and README's test table. Still open: round 3 below, the
> lead's reference-deck run and golden capture in the private repo. The as-built design lives in
> `geometry.py`'s docstring, the comments in `geometry.rules.toml` (one block per rule, every
> param) and SKILL.md's "The geometry gate"; this file is now history. Design below is corrected
> to what was built.
>
> Written 2026-10-04. The planner isn't the implementer: a `writer` builds each round in a
> worktree, a fresh `reviewer` checks each diff, and the lead runs the suites, the private
> reference-deck check and the merge. The previous PLAN.md (the watch guard) is history; it lives
> in git (`git show 411bec9:PLAN.md`), and its as-built design is in `docs/delegation.md`.

## Why

`deck-production` has a phase model and a core loop, but its "gate green" (SKILL.md) requires
"geometry has 0 violations on every touched slide", and no tool checks that. Screenshots miss the
defect class it targets (SKILL.md failure 2): in the reference deck, a map slide shipped place
labels whose captions had no `max-width` and no panel behind them, anchored about 95px apart, so
two labels' text ran into each other. It took four review rounds by eye. The gate measures the
rendered DOM and asserts numerically.

## Target

- `deckkit geometry <deck> [--slides id,...] [--json]` exits 1 on a slide reproducing that defect
  and 0 on the fixed version. On the private reference deck: the pre-fix commit's map slide
  fails, the slide as it stands passes, and every other slide's result is recorded as a golden.
- Stdlib-only Python, like every deckkit tool. No node, Puppeteer or Playwright.

## Design (as built)

**Driver: Python speaking CDP over `--remote-debugging-pipe`** (Hayden's call, 2026-10-04).
- Browser (`geometry.find_browser`, which `doctor` reuses): `env.chrome` when set, else the
  newest `chrome-headless-shell` in the Puppeteer cache
  (`~/.cache/puppeteer/chrome-headless-shell/*/chrome-headless-shell-linux64/chrome-headless-shell`),
  else `deckcfg.find_chrome` with `--headless=new`. Probed: the headless shell runs inside the
  Claude Code sandbox, while full Chrome aborts there (signal 6).
- Transport: fds 3 (commands in) and 4 (events out), NUL-delimited JSON. Probed gotcha: in
  `preexec_fn`, lift both pipe ends above 4 first, then `dup2` them onto 3 and 4, and pass
  `pass_fds=(3, 4)`. Passing the original fd numbers lets the child close 3 and 4, and the
  session hangs. The browser starts before the server thread, since `preexec_fn` is only safe
  while the process has one thread.
- Flags: `--no-sandbox --disable-gpu --disable-dev-shm-usage --hide-scrollbars --no-first-run
  --no-default-browser-check --user-data-dir=<tempdir> --remote-debugging-pipe`, window and
  viewport at the canvas size. Close with `Browser.close`; kill only the process we started.
- Serve the deck with `serve.py`'s handler on an ephemeral port (`127.0.0.1:0`) in a thread.
  Never `file://` (serve.py's docstring says why).
- One page load of `index.html?export`: wait for `Reveal.isReady()`, turn transitions off, check
  every configured selector parses (a typo is a config error, not a probe crash), and evaluate
  the probe file once. Then per slide, per fragment step from before the first fragment to the
  last: `Reveal.slide(h, v, f)`, finish running animations, and wait for what the slide paints
  with (fonts, images, svg images, video frames, url() backgrounds, the reveal slide background)
  within a 20 s settle budget, or exit 2 naming what did not load. A step that measures the same
  as an earlier one is not measured again.

**Probe: `scripts/geometry_probe.js`**, pure in-page functions returning JSON, no rules. Boxes
are client rects divided by `Reveal.getScale()`, minus the origin of the `.slides` element (the
canvas, not the section: with `center: true` reveal shifts a short slide down). It returns an
`elements` table (selector path, uid stable across steps, position, font size, group opacity and
the like) that everything else points into, plus:
- **texts:** each element with a direct non-whitespace text node, svg text included. Its boxes
  are the line rects from `Range.getClientRects()` over those text nodes, not the element box.
  The rules judge ink: a line rect trimmed to the em box, since a Range rect is the font's
  content area, taller than the glyphs.
- **markers:** elements matching `covers-marker`'s selectors (default `.pin, [data-geo=marker]`).
- **clipping:** elements with overflow hidden or clip whose content is larger than their box,
  with their boxes.
- the canvas margin (the `--margin-slide` token, resolved by the browser) and, per rule, which
  `exempt` selectors matched which texts.
- Hidden things (`display: none`, `visibility: hidden`, opacity 0, zero area) are skipped.
  Speaker notes (`aside.notes`) are never measured. There is no media list and no inferred
  background: contrast is measured on pixels instead (below).

**Contrast: a swatch map.** For each step where some text is judged, the canvas is screenshotted
five times: glyphs invisible (the backdrop, text-shadows and svg halos kept), every glyph as an
opaque black and then white swatch in place, and the glyph shapes isolated in black and white.
The swatches measure what group opacity, masks and overlays above the text do to a color, pixel
by pixel; the isolated shapes find each glyph's core pixels, so anti-aliasing never enters. The
text's declared color, carried through that map, is compared with the backdrop under each core
pixel, and the ratio at a low percentile must reach the bar. Each text is judged at the step
where it is most visible, then least hidden, so a fragment dimmed by design is judged at full
strength and a caption a later fragment covers (an r-stack) where it showed.

**Rules: `scripts/geometry.rules.toml`**, declarative, evaluated in Python. Each `[[rule]]` has
`id`, `severity` (`error` or `warn`), `enabled`, its own params, and `exempt` (CSS selectors whose
text that rule skips). A deck overrides them under `[geometry]` in `deck.toml`
(`geometry.disable = [ids]`, `geometry.<id>.<param> = ...`); a misspelled id or param is a config
error. `deckcfg.DEFAULTS` holds `geometry.rules` (the path), `geometry.slides` and
`geometry.disable`. As built:

| id | Fails when | Default |
|---|---|---|
| `text-overlap` | the ink of two text items intersects by more than `min_area` px² (4) and `min_depth` px (3) on both axes; nested items never count, and lines one flow stacked count only past `flow_overlap` em (0.3) | error |
| `covers-marker` | a text line rect intersects a marker's box by more than `min_area` (0) | error |
| `unbounded-abs-text` | running text in an absolutely positioned box that, lengthened, widens to fill all the room its anchor allows (a growth test, not a stylesheet read); h1 to h3 and labels of at most `label_chars` (24) are exempt | error |
| `text-contrast` | the measured WCAG ratio at `percentile` (5) is below `min_small` (4.5) or, for large text (`large_px` 24, or `large_bold_px` 18.66 at weight 700), `min_large` (3.0); under `min_pixels` (40) judged pixels a failure is an error only if the median fails too | error |
| `covered-text` | at least `min_hidden` (0.02) of a text's core pixels show nothing of the glyph, because something is painted above it | error |
| `safe-area` | a text line leaves the canvas inset by `margin` (`"auto"`: the `--margin-slide` token, else 96) by more than `tolerance` (2); text on an edge-hugging panel is measured by the panel's inset; `footer.src` and `[data-decor]` exempt | warn |
| `clearance` | ink overlaps shallower than `min_depth`, or independently placed text (different positioned boxes) sits closer than `min_gap` px (8) | warn |
| `clipped-text` | a text line runs past an overflow hidden or clip ancestor by more than `tolerance` (2) | error |

`text-on-media` was replaced by `text-contrast` and `covered-text` (see the decisions below).
The contrast bars below AA need a `reason`, printed every run. At regulated rigor the floor
holds: a bar below AA, the rule off or a warning, a percentile above 5, large-text sizes below
WCAG's, an exemption taking most of a slide's text, or a declared rigor below the derived one
without `rigor_reason` is a config error.

Exit 0 clean or warnings only, 1 on any `error`, 2 on a config error or a slide that does not
settle, 3 when no browser is found or it dies. Output, one line per violation:
`ERROR s05-map text-overlap  .label-a .caption x .label-b .name  (31x18 px)`, with `step 2/4`
after the slide when the finding is outside the final state, then
`geometry: E errors, W warnings on N slides`. `--json` prints one JSON object on the last line:
`errors`, `warnings`, `slides` (per-slide counts), `violations` (each with `slide`, `rule`,
`severity`, `subject`, `detail`, `step`) and `exit`.

**Hard constraint.** The fixed reference slide reports 0 errors. A rule that flags it is either
mis-scoped or has found a real defect. The second case goes to Hayden; it is never loosened
silently.

**Wiring (done).**
- `scripts/deckkit` registers `geometry`.
- `parity_check.collect()` records `facts["geometry"]`: per slide, per rule, error and warning
  counts, plus totals and the exit code. No ratios, subjects or steps, since contrast readings
  move by hundredths across renders. A run without a browser records `{"exit": 3}`, which the
  golden diff shows.
- SKILL.md names `deckkit geometry` in the gate text, has a section on what the gate checks, and
  the "cannot be executed yet" line no longer lists geometry.
- `doctor.py` reports the browser geometry would use, with the install hint when there is none.
- The `deck.toml` template carries a commented `[geometry]` example.
- No "S3" or plan-block names in shipped files.
- Out of scope: `forward_targets` detection (STATUS ties it to MUST/NEVER enforcement), and
  fonts and PDF (the next block).

**Privacy.** dotclaude is public and the reference deck is a client's. The in-repo fixture is
synthetic: same geometry (right-anchored label columns, captions without `max-width`, no panel,
anchors 95px apart, over an image) and a fixed twin (bounded captions on panel cards). The real
slide's before-and-after check and its golden stay in the private repo's `decks/_parity/`.

## Decisions after the first real-deck run (2026-10-04)

Round 1 passed its synthetic fixture and failed the reference deck: 21 errors on the fixed slide,
104 across a deck that shipped through review, and no rule saw the pre-fix defect. What changed:
- **Rules are judged by principle against the real deck**, never by per-slide exemptions. Small
  vs large text follows WCAG's large-text line; media means raster; in-flow siblings and ink depth
  replace raw box overlap; width bounds are found by a growth test (append words, see whether the
  box widens), not by reading stylesheets.
- **Contrast is measured, not inferred** (Hayden's call). `text-on-media`'s panel, scrim and
  shadow checks failed dark text on a bright photo and could not see Reveal slide backgrounds. It
  becomes `text-contrast`: hide the glyphs (keep their shadows), screenshot the slide, and compute
  the WCAG ratio of each text item's color against the pixels under its ink (4.5:1 small, 3:1
  large, on a low percentile so stray dots don't fail a line). As built it grew into the swatch
  map above, plus `covered-text` for text hidden under something painted above it.
- **The bar is WCAG AA by default; a deck may lower it** (Hayden's call). `[geometry.text-contrast]
  min_small` / `min_large` below AA need a non-empty `reason`, printed on every run like
  `rigor_reason`, and are refused (config error) when the deck's rigor is `regulated`. Measured on
  the reference deck: 114 errors, 86 of them two palette colors (an accent at 2.94:1, a source
  ink at 4.05:1), the rest photo captions, sources and kickers at 2.1 to 4.3:1.
- **Real finds on the reference deck are recorded, not fixed here** (Hayden's call). The golden
  holds them as known findings; the fixes belong to the deck's own repo and session.

## Rounds

1. **Core** (writer, done): `geometry.py`, `geometry_probe.js`, `geometry.rules.toml`, `deckcfg`
   defaults, the fixture deck, `tests/deck_production/`. Reviewer passes.
2. **Wiring** (writer, done): `parity_check`, SKILL.md, `doctor.py`, the `deck.toml` template,
   README's test table. Reviewer pass.
3. **Lead (open):** run the reference deck at its pre-fix commit (a temporary worktree of the
   private repo) and as it stands, then capture the golden and run `deckkit regress`.

## Verification

- `python3 -m unittest discover -s tests/deck_production -t tests/deck_production` passes
  sandboxed. The rule tests run on canned probe JSON, as an outcome by rule matrix (each rule
  fires on its bad case and stays quiet on its good one). The end-to-end tests drive Chrome
  over the fixture and skip with a reason if no browser is found. `test_parity_check.py` pins
  the regress facts on stubbed geometry output.
- `deckkit geometry <fixture> --slides bad` exits 1 with `text-overlap` and `unbounded-abs-text`;
  `--slides good` exits 0.
- Reference deck: pre-fix map slide fails, current slide 0 errors, `deckkit regress` green
  after the golden is captured, `deckkit lint` output unchanged.
