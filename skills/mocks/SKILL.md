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
   - `QUESTIONS` holds each decision the mock exists to settle, with `options` that switch the render live.
   - `CONTROLS` adds a button group to the top row for a choice that applies to the whole render.
   - `ABOUT` is HTML for the intro and any secondary notes, such as swatches.
3. **Inline everything** the render needs. A published page can't reach localhost. Inside `render`'s string, write `<\/script>`: a plain closing tag ends the page's own script.
4. **Run the check**, and fix what it reports until the last line is `LAYOUT_OK`:
   `python3 <skill dir>/scripts/layout_check.py <page>`
   It runs inside the sandbox, clicks every control, and needs headless Chromium; exit 2 prints how to install it. If the top row won't fit on one row, move a control into `QUESTIONS`. A `WARN` line names a control that changed nothing in the render: wire it into `render`, unless it only shows beside another option.
5. **Look at it** at laptop and phone frames before showing it. The check measures layout, not whether the render looks right.
6. **Publish** it as a plain page: the Artifact tool's quickstart with intent `other`, then publish the file. Skip this only when asked to. The local copy stays either way: it is the source for every change.

## With the Artifact tool and artifact-design

A clickable mock goes through this skill, not the Design type. Use the Design canvas only when Hayden asks for a canvas or artboards.

Load `artifact-design` before publishing. Its page contract applies, and the template already meets it. Two of its lines give way to this skill:
- The layout check runs before every publish, and again after every change, however many times that takes.
- Its call to avoid templated designs applies to the render, never to the shell.

To save picks across viewers, add the `db` capability through `artifact-capabilities`.

## Known edges

- A Phone frame on a big window leaves a very wide questions column.
- Fit stops at 100%, so a big monitor leaves space under the render. Larger would misstate the real size.
- The switch to one screen goes by width alone, so a wide, very short window gets a small render.
- Top-row buttons shrink to fit, below a touch target's size. Mocks are a desktop tool.
- The check runs Chromium only, at the page's default Zoom, and can't see published safe-area insets.
