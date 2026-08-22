---
name: ui-alignment
description: Hayden's discipline for aligning and centering visual elements so they look right, not just measure right. Use when centering or positioning anything visual (SVG text, textPath labels, a logo/seal/badge, kanji or icon glyphs), tuning a wordmark or mark, or whenever a measured "centered" still looks off. Covers optical-vs-geometric center, text-anchor advance-box vs ink, letter-spacing trailing advance, brush/tall-glyph tails, getBBox/getBoundingClientRect lying on curved text, measure-after-fonts-load, judge-at-deploy-size, hand-over-an-interactive-editor-when-contested, and recreate-against-a-reference.
---

# UI alignment

Make visual elements look aligned, not just measure aligned. The eye is the authority; the numbers are decoys. Each rule is a scar from centering a seal and its curved labels by the wrong method for a full day. This is the text/mark layer on top of `frontend-ui-discipline` — it owns render-before-you-show and measure-the-rendered-element; don't restate those here.

## Optical, not geometric — the eye is the authority
- **A measured "centered" that looks off is off.** Never argue the human out of what they see; the perception is the spec, the number is a proxy that is often wrong.
- **`text-anchor="middle"` centers the advance box, not the ink.** Per-glyph widths and side-bearings differ — a narrow "I" vs a wide "K" — so a geometrically centered word ("KOKIKAI") sits visibly off. Nudge it toward the heavier side until the *ink* looks centered.
- **`letter-spacing` adds trailing advance after the *last* glyph too**, so `text-anchor="middle"` centers a box wider than the visible word and pushes it toward the start. Compensate with `startOffset` / an x-nudge; don't trust the anchor.
- **Tall/brush glyphs fool the bounding box:** a downward tail (氣) drags the bbox centroid down, so centering the box floats the visible body high. Center the body by eye, not the box.
- **`getBBox()` and `getBoundingClientRect()` mis-report curved `<textPath>`** — they insist x≈50 on a label that plainly reads rotated off-center. Do not use them to arbitrate text centering.

## When a position is contested, hand over the controls
- **Disputed more than once → stop guessing in a render loop.** Build a slider/crosshair editor with a live preview at deploy size and a values readout; let the human drag it and read back the spec. One eye-set pass beats N guess-and-render rounds (the seal centering burned ~7–8 rounds; the editor settled it in one).
- **Don't substitute your eye on a headless screenshot for theirs.** Optical centering is their judgment to make; your job is to build the instrument, then apply the numbers they set.
- Same rule for layout/spacing: give an editable canvas, don't iterate position in code (see the `hand-hayden-a-canvas-for-layout` memory).

## Measure correctly, or not at all
- **Load the web font before reading any glyph metric:** `await document.fonts.load("<spec>", "<glyphs>")` then `await document.fonts.ready`. Metrics taken during font-tofu are identical fallback boxes, so any solve built on them is garbage (renders low/wrong).
- **A "center the bbox" solve is only as good as the metric under it.** For brush/display faces, prefer an optical nudge tested visually over a computed center.

## Judge at deploy size
- **Tune the asset at the size it ships** (a 62px corner logo at 62px), not at 20–30× zoom. Sub-pixel optical offsets are size-dependent: a big-render "fix" can be invisible or wrong at the shipped size. Keep a true-size preview in the loop from the start, not bolted on at the end.

## Recreate against the reference, not from memory of it
- **Rebuild a mark from a color-matched side-by-side (a blind diff), not from an idea of it.** Drift hides in plain sight — an extra ring, an asymmetric radius, an oversized glyph, a thin font where the original is bold brush — and you won't catch it freehand. A fresh-eyes diff will; it's worth demanding one.
- **Verify the actual font/material renders as you assume before you design an axis around it** (Yuji Syuku is a near-mincho serif, not a dramatic brush — one render up front kills the wrong assumption before it becomes a whole exploration).
- **Don't present visually indistinguishable variants as choices** (1px font-size steps); it spends attention without advancing the design.
