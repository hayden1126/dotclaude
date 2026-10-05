# PLAN: deck-production geometry gate

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

## Design

**Driver: Python speaking CDP over `--remote-debugging-pipe`** (Hayden's call, 2026-10-04).
- Browser: prefer `chrome-headless-shell` (Puppeteer cache:
  `~/.cache/puppeteer/chrome-headless-shell/*/chrome-headless-shell-linux64/chrome-headless-shell`),
  then `deckcfg.find_chrome` with `--headless=new`. Probed: the headless shell runs inside the
  Claude Code sandbox, while full Chrome aborts there (signal 6). `env.chrome` still wins when set.
- Transport: fds 3 (commands in) and 4 (events out), NUL-delimited JSON. Probed gotcha: `dup2`
  the pipe ends onto 3 and 4 in `preexec_fn` and pass `pass_fds=(3, 4)`. Passing the original
  fd numbers lets the child close 3 and 4, and the session hangs.
- Flags: `--no-sandbox --disable-gpu --disable-dev-shm-usage --hide-scrollbars
  --user-data-dir=<tempdir> --remote-debugging-pipe`, window and viewport at the canvas size.
  Close with `Browser.close`; kill only the process we started, by its recorded PID.
- Serve the deck with `serve.py`'s handler on an ephemeral port (`127.0.0.1:0`) in a thread.
  Never `file://` (serve.py's docstring says why).
- Per slide: open `index.html?export`, wait for `Reveal.isReady()`, `document.fonts.ready` and
  every `img` complete, `Reveal.slide(h, v, <last fragment>)` so fragments are in their final
  state, two `requestAnimationFrame`s, then evaluate the probe.

**Probe: `scripts/geometry_probe.js`**, a pure in-page function returning JSON, no rules. Port
the normalization from the reference repo's `export_extract.js`: client rects divided by
`Reveal.getScale()`, minus the section's origin, so boxes are in canvas pixels. It returns:
- **text items:** each element with a direct non-whitespace text node. Its boxes are the line
  rects from `Range.getClientRects()` over those text nodes, not the element box, because a
  block's box spans its container and would report false overlaps. Plus a selector path, the
  computed `position`, `max-width`, `width` (specified, via the inline style or the matched
  rule when cheap; otherwise computed), `text-shadow`, and the effective background: the first
  ancestor up to the section with a non-transparent `background-color` or a `background-image`.
- **markers:** elements matching the rules' marker selectors (default `.pin, [data-geo=marker]`).
- **media:** visible `img`, `video`, `canvas`, and `svg` that isn't inside text.
- **clipping:** elements with overflow hidden or clip whose scroll size exceeds the client size
  and that contain text.
- Hidden things (`display: none`, `visibility: hidden`, opacity 0, zero area) are skipped.
  Speaker notes (`aside.notes`) are never measured.

**Rules: `scripts/geometry.rules.toml`**, declarative, evaluated in Python. Each `[[rule]]` has
`id`, `severity` (`error` or `warn`), `enabled` and its own params. A deck overrides them under
`[geometry]` in `deck.toml` (`geometry.disable = [ids]`, `geometry.<id>.<param> = ...`);
`deckcfg.DEFAULTS` gains `geometry.rules` (the path) and `geometry.slides` (default all). The
starting set:

| id | Fails when | Default |
|---|---|---|
| `text-overlap` | line rects of two different text items intersect by more than `min_area` px² (default 4); nested items and the same item never count | error |
| `covers-marker` | a text item's line rect intersects a marker's box | error |
| `unbounded-abs-text` | an absolutely positioned element containing text has `max-width: none` and no specified width, so its text width is decided by content alone | error |
| `text-on-media` | a text line rect intersects media, the text has no panel background and no `text-shadow` | error |
| `safe-area` | a text line rect leaves the canvas inset by `margin` (default: the `--margin-slide` token, else 96) by more than `tolerance` (default 2) | warn |
| `clearance` | two text items closer than `min_gap` px (default 8) without overlapping | warn |
| `clipped-text` | text cut off by an overflow-hidden ancestor | error |

Exit 1 on any `error`; `warn` prints but exits 0, like lint. Output, one line per violation:
`ERROR s05-map text-overlap  .label-a .caption x .label-b .name  (31x18 px)`, then
`geometry: E errors, W warnings on N slides`. `--json` prints one JSON object per run on the last
line (lint's convention).

**Hard constraint.** The fixed reference slide reports 0 errors. A rule that flags it is either
mis-scoped or has found a real defect. The second case goes to Hayden; it is never loosened
silently.

**Wiring.**
- `scripts/deckkit:42` already registers `geometry`; it stops saying "not built yet" once the
  script exists.
- `parity_check.collect()` gains `facts["geometry"]` (per-slide error and warning counts plus
  the exit code), so `deckkit regress` holds it as a golden.
- SKILL.md: the gate text names `deckkit geometry`, and the "cannot be executed yet" line (`:142`)
  drops geometry.
- `doctor.py` reports the headless shell.
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
  large, on a low percentile so stray dots don't fail a line).
- **Real finds on the reference deck are recorded, not fixed here** (Hayden's call). The golden
  holds them as known findings; the fixes belong to the deck's own repo and session.

## Rounds

1. **Core** (writer): `geometry.py`, `geometry_probe.js`, `geometry.rules.toml`, `deckcfg`
   defaults, the fixture deck, `tests/deck_production/`. Reviewer pass.
2. **Wiring** (writer): `parity_check`, SKILL.md, `doctor.py`, README's test table. Reviewer pass.
3. **Lead:** run the reference deck at its pre-fix commit (a temporary worktree of the private
   repo) and as it stands, then capture the golden and run `deckkit regress`.

## Verification

- `python3 -m unittest discover -s tests/deck_production -t tests/deck_production` passes
  sandboxed. The rule tests run on canned probe JSON, as an outcome by rule matrix (each rule
  fires on its bad case and stays quiet on its good one). One end-to-end test drives Chrome
  over the fixture and skips with a reason if no browser is found.
- `deckkit geometry <fixture> --slides bad` exits 1 with `text-overlap` and `unbounded-abs-text`;
  `--slides good` exits 0.
- Reference deck: pre-fix map slide fails, current slide 0 errors, `deckkit regress` green
  after the golden is captured, `deckkit lint` output unchanged.
