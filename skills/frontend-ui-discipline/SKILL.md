---
name: frontend-ui-discipline
description: Hayden's discipline for building web UIs that work on mobile and desktop without the usual bugs. Use when writing or reviewing HTML/CSS/JS for a site or dashboard, styling layout (sticky/fixed headers, flex/grid, overlays), adding search/filter/highlight, i18n/language toggles, or any touch-vs-desktop interaction. Covers verify-in-real-browser-at-both-widths, measure-don't-assume, sticky/scroll-margin math, touch :hover pitfalls, single-source-of-truth state, overlays, highlight, and i18n.
---

# Frontend UI discipline

Build web UIs that work on mobile and desktop the first time. Each rule is a scar from a real bug. (The bella-specific gated single-file dashboard pattern that seeded these rules now lives with that project, in the `bella-dashboard` skill in the bella repo.)

## Verify in a real browser, at both widths
- **Never claim done from the code alone.** Build, reload, assert state in the browser (`chrome-devtools` `evaluate_script`), screenshot, then commit. Evidence, not assertion.
- **Design mocks especially — a CSS read cannot see a rendered visual.** Filter/displacement/blend effects (`feTurbulence`, masks, `mix-blend`) can silently shred a shape into fragments; a one-second screenshot catches what hand-reading the stylesheet never will. Never present a visual you have not seen rendered.
- **A fix isn't done until it's re-rendered and back-ported.** Re-shoot after every change — one fix can spawn another (an overlap patch that adds a visible seam) — and propagate a shared-asset fix to every copy that carries it (artboards, exports, the canvas), or the copies silently drift. For centering/optical-alignment work see the `ui-alignment` skill.
- **Test mobile AND desktop every time:** 390×844 and ≥1024. Bugs that appear at only one width are the common case.
- **Ship small verified increments** — one change, verify, commit.
- **Verification traps:** smooth-scroll is async (wait, then measure); read a live `Highlight`'s size *before* clearing the search; `curl` needs `--compressed` or a gzipped page reads as empty.

## Measure the element; don't trust the CSS number
- **Read the rendered size, never the declared one.** `min-height` grows with padding and borders; set offsets from `offsetHeight`/`getBoundingClientRect()`, not the stylesheet value. If you catch yourself copying a `top:` from a `min-height`, stop and measure.
- **Pinned layout is offset math:** a sticky element sits at `top: Σ(sticky heights above it)`; stacked bars add up; leave a small gap so it floats, not butts.
- **Anchored jumps need `scroll-margin-top` ≥ the stacked sticky height**, or `href="#id"` lands under the header.

## Touch is not hover — design for the finger first
- **`:hover` latches on touch:** it stays applied after a tap until you tap elsewhere. Drop hover colour changes or gate them in `@media (hover:hover)`.
- **`font-size:16px` on every text input**, or iOS zooms the page on focus.
- **≥44px tap targets** — small padding on a 13px button is not tappable. Lean on native `type="search"` for the clear affordance.
- **Off-canvas drawers need focus trap + Escape + backdrop close + body scroll-lock**, and restore focus to the opener on close.

## One source of truth for state
- **Compose filters; don't stomp them.** A row is visible only if it passes ALL active filters; funnel every change through one apply path that also re-runs dependent effects (re-highlight). Two paths writing the same DOM state will fight.
- **Reference/always-on sections opt out of generic hide-empty logic** and show an inline empty-state — never let filtering produce a blank void.
- **Controls duplicated across breakpoints wire by class, not id**, and sync through that one apply path so the copies never diverge.
- **Edit copy, not identifiers:** when rewording, change only reader-visible strings; leave JSON keys, CSS classes, HTML ids, and function names alone so anchors, search, and highlight keep working.

## Overlays, highlight, i18n
- **Reveal without reflow:** `position:absolute`, kept painted at `opacity:0` (not `display:none`), gated `@media(hover:hover)`; `pointer-events:auto` on the *revealed* state only. Guard tap-to-reveal against taps on links (`closest('a')`) and mid-selection (`!getSelection().isCollapsed`).
- **Highlight without mutating the DOM:** CSS Custom Highlight API + a `TreeWalker` building `Range`s beats `<mark>` spans that clobber nested markup; skip chrome subtrees (`.prov`, `.badge`, the input) and `display:none` nodes; degrade to a no-op on old browsers.
- **i18n swaps text in place:** ship both languages inline, swap `textContent` + `placeholder` + `document.title` + SVG `<text>`, persist in `localStorage`, fall back to English, then **re-run search/highlight** — the swap replaced the nodes the ranges pointed into. Keep numbers, IDs, and brand names language-neutral; a single-label toggle shows the language you'd switch TO.

## Robustness the reader never notices
- **Never encode meaning by colour alone:** triple-encode status (colour + glyph + word); render a warning as a box treatment (border + corner glyph), not a pill, so flagging a card never reflows it.
- **Don't depend on assets the viewer might lack:** inline SVG beats an emoji that renders as tofu; add an `@supports not (backdrop-filter…)` solid fallback; ship a `<noscript>` fallback and `noindex` private pages.
- **Hide text from sight without hiding it from screen readers:** clip it (off-screen / `clip-path`), never `display:none` — clipped text is still announced (e.g. a badge showing only its glyph on mobile).
- **Keyboard parity:** non-interactive cards get `tabindex="0"` so `:focus-within` reveals what hover does; `/` focuses search.
- **Wire with `addEventListener`, never inline `on*`** (CSP); prototype visual variants live (inject CSS, screenshot) so the human picks from real renders.

## Responsive specifics
- **`gap` shorthand sets both axes** — a wrappable row wants `gap: 3px 14px`, not `gap:14px`.
- **Reflow by viewport width, not device detection** — media queries plus the viewport meta cover tablet, rotation, and resized windows that a mobile-vs-desktop split misses.
- **`100dvh`, not `vh`,** for full-height mobile surfaces.
- **Wide tables become stacked cards on phones** (`thead` clipped, `td::before{content:attr(data-label)}`); never scroll a data table sideways.
- **Charts: caption and units in HTML above a fluid `viewBox` SVG**, direct-label bars, value flipped inside the bar past ~50% width so it never clips.
