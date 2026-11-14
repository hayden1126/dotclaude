---
name: mocks
description: Use when building a clickable design mock, mockup or UI prototype in any project, a page someone clicks through to compare looks, layouts, themes or device sizes before the real thing is built. Not for test mocks or stubs, mock data or mock servers, mock exams, production pages, or static artboards on a canvas.
---

# Mocks

Every clickable mock uses one layout, so it is easy to view, use and customize. On a wide window it is one screen with no page scroll: a one-row control bar, the render fitted to the window and fixed in place, and the questions beside it as the only scroller. Under 1,101 px the columns stack and the page scrolls.

The shell is fixed. Design freedom goes into the render.

## Build a mock

1. **Copy** `<skill dir>/template/mock.html` to the project: `.lane/mock/` in a lane, otherwise wherever the project keeps design work.
2. **Set the `<title>` and fill in the config block** at the top of its script. Leave everything else alone:
   - `render(state)` returns the full HTML of the screen, built from the project's own tokens, fonts and real screens.
   - `FRAMES` are the device sizes. The render sits in an iframe of that size, so its media queries see the frame's width.
   - `MODES` are the themes `render` honours through `state.mode`. One entry hides the Mode buttons.
   - `SCREENS` are the screens the mock shows, as a top-row group; `render` gets `state.screen`. Leave it out, or give one entry, and the group hides.
   - `QUESTIONS` holds each decision the mock exists to settle, with `options` that switch the render live. An optional `screens: [...]` lists where the question's subject shows: changing its answer jumps to the first listed screen when the current one isn't listed, and its box gets a "Shows on" row of buttons that jump to each.
   - `CONTROLS` adds a button group to the top row for a choice that applies to the whole render. With `corner: true`, the group sits in the render's corner beside the zoom instead. Its label can't be `frame`, `mode`, `zoom`, `screen` or `answers`: the shell keeps its own state under those names.
   - `ABOUT` is HTML for the intro and any secondary notes, such as swatches.

   The shell adds two pieces to every mock. The corner zoom has Fit, 100%, 200% and 300%; when the zoomed render passes the frame, drag it to pan, and the scroll positions (the render's page and any element in it that scrolls) hold while the frame and screen stay the same. Give an element that scrolls an id, and its position holds even when an answer adds or drops something above it. The "Copy choices" button copies each question's answer as plain text, to paste back in chat.

   The config can't reach the shell's code: the shell runs in its own scope. Everything a mock needs goes through these fields and `render(state)`.
3. **Inline everything** the render needs. A published page can't reach localhost. Inside `render`'s string, write `<\/script>`: a plain closing tag ends the page's own script. Screenshots in a mock are lossless (PNG, or lossless WebP): lossy compression smears small UI text, and lossless costs only about 10% more on flat UI.
4. **Run the check**, and fix what it reports until the last line is `LAYOUT_OK`:
   `python3 <skill dir>/scripts/layout_check.py <page>`
   It runs inside the sandbox, clicks every control, and needs headless Chromium. Exit 2 means it couldn't judge the page: it says why, and for a missing browser how to install one. If the top row won't fit on one row, move a control to the corner (`corner: true`) or into `QUESTIONS`. A `WARN` line names a control that changed nothing in the render: wire it into `render`, unless it only shows beside another option. It may also mean an option that only shows on another screen: give that question `screens`.
5. **Look at it** at laptop and phone frames before showing it. The check measures layout, not whether the render looks right.
6. **Publish** it as a plain page: the Artifact tool's quickstart with intent `other`, then publish the file. Skip this only when asked to. The local copy stays either way: it is the source for every change.

## Mocks built from files

A big mock may keep its config and generated assets in separate files and splice them in with a script. Splice or slice between the `/* ==== MOCK CONFIG` and `/* ==== END OF MOCK CONFIG` markers, never at a `<script>` tag: a render's string can hold scripts of its own.

## Patterns

- Comparing typefaces in place on real screens, without shipping the fonts: read `<skill dir>/references/type-in-place.md`.

## With the Artifact tool and artifact-design

A clickable mock goes through this skill, not the Design type. Use the Design canvas only when Hayden asks for a canvas or artboards.

Load `artifact-design` before publishing. Its page contract applies, and the template already meets it. Two of its lines give way to this skill:
- The layout check runs before every publish, and again after every change, however many times that takes.
- Its call to avoid templated designs applies to the render, never to the shell.

To save picks across viewers, add the `db` capability through `artifact-capabilities`.

## Known edges

- A Phone frame on a big window leaves a very wide questions column.
- Fit stops at 100%, so a big monitor leaves space under the render. Larger would misstate the real size.
- Zoom above 100% enlarges the paint and doesn't reflow the render: its media queries still see the frame's width.
- Drag to pan starts after a few pixels of movement. It never starts on a control (by tag, ARIA role or `onclick`), on an element with its own cursor such as `pointer` or `grab`, or on anything marked `data-no-pan`: add that to a render's own draggable or clickable piece that has none of these.
- The corner control sits over the render's bottom-left, so it covers what a render draws there, such as the first tab of a phone's bottom tab bar, at every zoom.
- The switch to one screen goes by width alone, so a wide, very short window gets a small render.
- Top-row buttons shrink to fit, below a touch target's size. Mocks are a desktop tool.
- The check runs Chromium only, expects the page to open at Fit, and can't see published safe-area insets.
- It clicks each control from the page's defaults, not every combination.
- `WARN` is a hint: it can't see a canvas redrawn in place.
