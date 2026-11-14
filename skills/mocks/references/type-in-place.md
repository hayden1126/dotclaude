# Type in place

A recipe for comparing heading or display typefaces on a product's real screens, inside a mock.

## When to use it

Use it when the candidate fonts are licensed and can't ship inside a published page. The page carries pictures of the type, never font files. A mock that can embed its fonts doesn't need this: set them in `render` directly.

## Method

1. **Capture the real screens** with each heading's text made invisible. Run a headless browser on a local build with test data. Wrap each heading's text in a span with `color: transparent`, so the layout is unchanged, then screenshot.
2. **Record each heading's position** in the same run: its left edge and its baseline. The baseline is the span's rect top plus the `fontBoundingBoxAscent` that canvas `measureText` returns for the span's computed font.
3. **Render each candidate face offline** at the heading's real size, as a transparent PNG. Pillow with RAQM layout works; render at 2x for sharpness. Record the image's own baseline and left padding.
4. **Place the pictures in the mock.** Over each screenshot, position the picked face's PNG absolutely, so its baseline and left edge match the recorded ones.

Wire it to the config:
- One question per group of headings picks the face.
- `SCREENS` lists the captured screens.
- Each question's `screens` names the screens where its headings appear.

## Pitfalls

- **Split text nodes.** A framework may split a template's text into several text nodes. Merge adjacent text nodes before wrapping, or the span covers only part of the heading.
- **Ghost copies.** A page may hold hidden or scaled duplicates of a heading, for measuring or animation. Dedupe them, and apply a copy's scale to its size and position.
- **Saved theme.** A signed-in account's saved theme can beat the theme the capture sets in `localStorage`. A light run once came out dark. Check each capture's theme before using it.
- **Lossless images.** Screenshots and masks go lossless (PNG, or lossless WebP). Lossy compression smears small text and the edges the overlay has to match.
