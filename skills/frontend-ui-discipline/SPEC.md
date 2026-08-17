# Skill extraction + spec: `frontend-ui-discipline` (+ self-contained-dashboards reference)

> **Migration note (2026-08-17):** the bella-specific `references/self-contained-dashboards.md` described
> below was later moved out of this (general) skill into the project-scoped `bella-dashboard` skill in the
> bella repo (`bella/.claude/skills/bella-dashboard/references/`), alongside the streaming-chat and CJK
> references added the same day. This SPEC is kept as the original authoring record; Part B's content now
> lives with that project. This skill is now general-only.

## Context

This session built a stack of mobile+desktop UI features on the Bella president-briefing dashboard (floating glass search, in-place highlight, EN/中文 toggle, cross-links) and fixed a long run of real UI bugs. The user wants that hard-won knowledge captured as a reusable **discipline skill** for building good, bug-free UIs (desktop and especially mobile). Decisions: **both layers** — a general web-UI discipline skill plus a companion reference for the specific self-contained-dashboard pattern; and **extract + spec only** now (a fresh session writes the actual SKILL.md, since context is ~60% full). This file is the durable source material so nothing is lost across the `/clear`.

## Deliverable shape (for the fresh session)

- **First, re-explore before drafting.** Run another exploration pass (dispatch an Explore agent) over `dashboards/president-briefing/build.py` — especially its rationale comments (`/* ... */` in the CSS, `//` in the JS) and the built HTML — plus a diff of this session's commits, to surface any design decisions Parts A–C still missed. Fold anything new into the skill. Two passes already found gaps (Part C was the second); assume a third will find more.
- **Author at** `/home/hayden/dotclaude/skills/frontend-ui-discipline/` (version-controlled dotfiles), then **symlink** `~/.claude/skills/frontend-ui-discipline` → it (mirrors every existing skill). Confirm final name with Hayden; alternatives: `web-ui-craft`, `building-web-ui`.
- **Files:** `SKILL.md` (general discipline, terse) + `references/self-contained-dashboards.md` (the pattern specifics + bug catalogue). Split per `superpowers:writing-skills`: keep principles <~50 lines inline, push heavy reference out.
- **Frontmatter:** only `name` + `description`, ≤1024 chars, kebab-case, name == folder. 
- **Voice:** match Hayden's existing discipline skills (`coding-practices`, `research-discipline`): H1 in sentence case, one framing line, themed `##` sections, rules as **bold imperative lead-in + one crisp sentence**, self-correction triggers ("If you catch yourself thinking X, stop and Y"), Bad/Good pairs. Under ~500 words for SKILL.md; the reference file carries the bulk.
- **Testing (Iron Law from `superpowers:writing-skills`):** before finalizing, pressure-test with subagents — give a fresh agent a mock UI task and see whether the description triggers the skill and whether the body actually steers it. Iterate RED→GREEN. `wc -w` to check length.

### Draft `description` (triggers only + Hayden's brief "covers" clause)
> Hayden's discipline for building web UIs that work on mobile and desktop without the usual bugs. Use when writing or reviewing HTML/CSS/JS for a site or dashboard, styling layout (sticky/fixed headers, flex/grid, overlays), adding search/filter/highlight, i18n/language toggles, or any touch-vs-desktop interaction. Covers verify-in-real-browser-at-both-widths, measure-don't-assume, sticky/scroll-margin math, touch :hover pitfalls, single-source-of-truth state, and self-contained-dashboard specifics.

---

## PART A — General web-UI discipline (source for `SKILL.md`)

Each principle below pairs the **rule** with the **bug in this session that taught it** (keep the bug as the "why"; a rule with a scar is remembered). Order roughly by how often it bites.

1. **Verify in a real browser at BOTH widths before claiming done.** Every change was: build → reload → assert state with `chrome-devtools` `evaluate_script` → screenshot → only then commit. Test mobile (`resize_page` 390×844) AND desktop (≥1024). Bugs that only showed at one width were common. Evidence, not assertion.

2. **Measure the rendered element; never trust the CSS number.** The pinned search bar used `top:48px` = the mnav's `min-height:48px`, but the mnav actually rendered **55px** (8px padding + 38px button + border). Result: 7px overlap. Fix: read `el.offsetHeight` in the browser, set `top:55px`. Rule: `min-height` ≠ rendered height; padding/among content grows it. Measure with `getBoundingClientRect()`/`offsetHeight`.

3. **Sticky/pinned layout is offset math — do it explicitly.** A pinned element sits at `top: <height of everything sticky above it>`. Stacked sticky bars add up (mnav 55 + gap 8 → bar at 63). Anchored jumps (`href="#id"`) land UNDER sticky headers unless the target has `scroll-margin-top` ≥ the stacked sticky height (sections used 121px on mobile; registry rows 120px mobile / 18px desktop). Add a small gap so a pinned bar floats rather than butts against the bar above it.

4. **Touch is not hover; design for the finger first.** `:hover` **latches** on touch devices — it stays applied after a tap until you tap elsewhere (the language toggle stayed gold forever after one tap). Fix: drop hover color changes, or gate them in `@media (hover:hover)`. Also: `font-size:16px` on inputs to stop iOS zoom-on-focus; ≥44px tap targets; rely on `type="search"` native clear; off-canvas drawer needs a focus trap + Escape + backdrop close.

5. **Don't depend on assets/fonts the viewer might not have.** The 🌐 emoji rendered as a tofu box (no emoji font in headless/some devices) → replaced with an **inline SVG** globe (strokes = `currentColor`). CJK uses a system font stack appended into `--font-sans`/`--font-serif` (embedding a CJK webfont is multi-MB). For a gated/self-contained page, inline everything (CSS/JS/fonts as base64) so there are no external requests.

6. **One source of truth for visibility/state; compose filters, don't stomp them.** The text search and the registry source chips each wrote `.reg-row` display independently, so clicking a chip discarded the active search and dropped the highlight. Fix: a row is visible only if it satisfies **all** active filters (text AND source); funnel every change through one apply path (`runSearch(currentQuery())`) that also re-runs dependent effects (re-highlight). If two code paths set the same DOM state, expect them to fight.

7. **Special sections need explicit exemptions and empty states.** A generic "hide any section whose rows are all filtered out" rule silently vanished the full fact registry (a reference section). Fix: exempt it by id, and show an inline "no rows match" note instead of disappearing. Rule: reference/always-on sections opt out of generic hide logic; never let filtering produce a blank void.

8. **`gap` shorthand sets BOTH axes.** `.sec-head{gap:14px}` gave a wrapped subheading 14px of vertical space (looked broken) while inline ones were fine. Fix: `gap:3px 14px` (row-gap / column-gap). Rule: when a flex/grid row can wrap, set row and column gaps separately.

9. **Overlays that reveal on hover/tap are `pointer-events:none` — interactive children need it turned back on.** The provenance overlay stayed `pointer-events:none` even when shown (so taps pass through to toggle the card); links inside it were dead. Fix: add `pointer-events:auto` to the *revealed* overlay rules only (not the hidden state, or invisible links capture clicks). The card's tap handler already lets links through via `if(e.target.closest('a')) return;`.

10. **Highlight text without mutating the DOM.** Used the **CSS Custom Highlight API** (`CSS.highlights.set('search-hit', new Highlight())`, `::highlight(search-hit){background;color}`, a `TreeWalker` building `Range`s per match). It avoids wrapping `<mark>` spans that would clobber nested markup (badges, provenance, F-IDs) and break `textContent` search. Skip excluded ancestors (`.prov`,`.badge`,`.fid`) and `display:none` nodes in the walker. `::highlight()` only supports text props (background-color, color, text-decoration). Degrades to no-op on old browsers (filtering still works).

11. **i18n = swap text in place, with fallback.** Ship both languages inline: a `t(en, zh)` helper emits `<span class="t" data-en data-zh>EN</span>`; `setLang()` swaps `textContent` for every `.t`, plus input `placeholder` (`data-ph-en/zh`), mobile `data-label` (`data-label-zh`), and `document.title` (`data-title-en/zh` on `<html>`); persist in `localStorage`; re-run the search/highlight after swapping. Missing translation falls back to English automatically. Keep numbers, IDs, currency, and brand names language-neutral. SVG `<text class="t" data-en data-zh>` works for chart labels too. For a **single-label** language switch, show the language you'd switch TO (the target), with a globe, not the current one.

12. **Wire with `addEventListener`, never inline `on*` handlers** (CSP-friendly; the whole file already followed this — keep the convention).

13. **Prototype visual variants live, let the human pick.** For the search-bar size/shape, mocked ~4 variants by injecting CSS in the browser and screenshotting each, then asked via `AskUserQuestion` with previews. Faster and truer than describing options.

14. **Know the verification traps.** (a) Smooth-scroll is async — measuring position right after a click reads a mid-animation value; wait (`setTimeout`) then assert. (b) A live `Highlight` object read AFTER you cleared the search reports size 0 — capture values before mutating. (c) Cloudflare serves gzip; `curl` without `--compressed` looks empty even when content is live — always `curl -s --compressed`.

15. **Ship in small verified increments.** One change → build → verify in browser → commit → deploy → verify live (`/`→200, gated path→302, grep the served HTML for the new markup). For parallelizable non-edit work (translation), fan out subagents writing **disjoint** fragment files, then merge single-threaded — never parallel edits to one shared file. Gate sensitive content (translations of IR/defense prose) on a human review before deploy.

---

## PART B — Self-contained dashboards (source for `references/self-contained-dashboards.md`)

The specific pattern this dashboard uses, worth its own reference:

- **One build script → one self-contained HTML.** `build.py` reads `content.json` and emits HTML via f-strings; CSS is one `r"""..."""` constant, JS another; fonts are base64 `@font-face` data URIs. Zero external requests. Why: the page is served behind a Cloudflare Access gate, and inlining means no side-loaded asset can escape the gate.
- **Two variants from one function, split at build time.** `build(internal, sibling)` filters facts by `audience=="public"` for the investor file and drops internal sections; internal strings never appear in the public HTML (no view-source leak). Verify no-leak with `grep` on the built investor file.
- **Fact registry + F-IDs + provenance.** Every number traces to an `F-NNN` id; a `.prov` overlay reveals source/F-ID on hover/tap; a full registry table lists all facts with source chips. Cross-links: F-IDs → `#reg-<fid>` rows (rows carry that id, land with `:target` highlight); registry Section cell → `#<section>`.
- **i18n mechanism specifics.** `_zh` sibling keys in `content.json` (`claim_zh`, etc.); `t()`/`bi()`/`bi_field()` helpers; UI/section/chart Chinese inline in `build.py`; CJK via appended system font stacks. See Part A #11.
- **Build/deploy runbook.** From repo root: `.venv/bin/python dashboards/president-briefing/build.py` (the shell cwd resets between tool calls — `cd /home/hayden/code/bella` first). Deploy from the dashboard dir: `npm run deploy` (wrangler; **run build first**, it isn't wired into the npm script). Only `site/` deploys. Full contract in `dashboards/president-briefing/DEPLOYMENT.md`. Cross-ref memory `[[bella-president-dashboard-deployed]]`.

## PART C — Inherited design decisions (predate this session; keep them in the general SKILL.md)

These were already baked into `build.py` with documented rationale before this session. They are general UI craft, not dashboard-specific, and belong in the general discipline — I initially under-captured them because I focused on our diffs.

**Accessibility & robustness**
- **Never encode meaning by colour alone.** Every status badge carries a glyph AND a word; warnings are a box treatment (border recolour + a corner glyph + the word in the overlay), never a colour-only pill. Triple-encode status: colour + shape/glyph + text. (WCAG 1.4.1.)
- **Progressive enhancement — ship a no-JS fallback.** A `<noscript>` stylesheet replaces the JS off-canvas drawer with an always-visible static pill TOC on mobile; the page stays readable and navigable with JS disabled. Private page also sets `<meta name="robots" content="noindex,nofollow">`.
- **Full ARIA + focus management on the drawer/dialog.** Open sets `role="dialog"`+`aria-modal`, moves focus inside, **traps Tab** (first/last wrap), closes on Escape and backdrop, and **restores focus** to the opener (`lastFocus`) on close; `aria-expanded`/`aria-controls` on the toggle. `aria-live` on the "you are here" label and the match count; `aria-hidden` on decorative glyphs; `role="img"` on SVG charts; `role="note"` on overlays. Keyboard: `/` focuses search; `:focus-visible` outlines everywhere, never removed.
- **Reveal overlays without reflow (the origin of the pointer-events/touch-hover bugs).** `.prov` is `position:absolute` so revealing source/F-IDs never resizes the card; it fades via `opacity` and is **kept painted** (`opacity:0`, not `visibility:hidden` or `display:none`) so the mono glyphs are pre-rasterized and pill+text rise together with no first-reveal flicker; reveal is gated with `@media(hover:hover)` so a sticky touch `:hover` can't fight the tap-toggle class.

**Responsive layout**
- **Charts: put the caption/units in HTML above the SVG, not inside it** — text stays legible and wraps on narrow screens. Fluid SVG (`viewBox` + `preserveAspectRatio` + `height:auto`, `max-width`); direct-label bars (no axis); a wide bar's value renders INSIDE the bar so it never clips the viewport.
- **Mobile: turn wide tables into stacked cards** — the registry `<table>` becomes block cards on phones (`thead` visually hidden via clip, per-cell labels via `td::before{content:attr(data-label)}`). Never let a data table scroll sideways on a phone.
- **Tune density per breakpoint** — KPI tiles go 2-up on mobile to halve the hero scroll; the rail narrows on tablet; fact cards collapse to claim-line / value-line rows. `grid-template-columns: repeat(auto-fill, minmax(Npx, 1fr))` reflows without extra media queries.
- **Use `100dvh` (not `vh`) for full-height mobile surfaces** (accounts for browser chrome). Sticky-offset rules chain via combinators and get overridden per breakpoint.

**Typography & polish**
- **`font-variant-numeric: tabular-nums`** so figures align in columns; `-webkit-font-smoothing:antialiased`; self-hosted subset fonts, base64-inlined.
- Single centered `max-width` content column; consistent radii (8–12px); one accent colour reused for focus rings + links.
- **F-IDs are plumbing, not reading material** — surfaced on demand via the overlay everywhere, kept always-on only in the registry (the lookup table). Information-density decision: don't show provenance inline where it competes with the number.

## The bug catalogue (put as a table in the reference file — the skill's spine)

| Symptom | Root cause | Fix | Rule |
|---|---|---|---|
| Pinned bar overlaps banner by ~7px | `top` set from `min-height`, not rendered height | Measure `offsetHeight` (55px), set `top:55` | Measure, don't assume |
| Toggle stays gold after one tap | `:hover` latches on touch | Remove hover color / `@media(hover:hover)` | Touch ≠ hover |
| Globe shows as tofu box | Relies on system emoji font | Inline SVG icon | No unseeable font deps |
| Clicking source chip drops search + highlight | Two filters both write row display | Combine (AND) via one apply path + re-highlight | Single source of truth |
| Registry section vanishes on search | Generic "hide empty section" ate the reference table | Exempt by id + inline empty-state note | Special sections opt out |
| Big gap under a wrapped subheading | `gap:14px` sets row gap too | `gap:3px 14px` | gap = both axes |
| Links inside revealed overlay dead | `.prov` stays `pointer-events:none` | `pointer-events:auto` on revealed state only | Overlay interactivity |
| Anchored jump lands under sticky bars | No `scroll-margin-top` | Add margin ≥ stacked sticky height | Sticky offset math |
| Highlight would clobber nested markup | `<mark>` wrapping mutates DOM | CSS Custom Highlight API + TreeWalker | Highlight without mutation |
| `curl` shows empty page though live | Cloudflare gzip | `curl --compressed` | Verification traps |
| Position wrong right after click | Smooth-scroll async | Wait, then measure | Verification traps |

## Verification (of the finished skill, in the fresh session)

1. `wc -w SKILL.md` under ~500 words; reference file can be longer.
2. Frontmatter valid: `name` == folder, kebab-case, `name`+`description` only, ≤1024 chars.
3. Subagent pressure test (per `superpowers:writing-skills`): give a fresh agent a mobile-UI task ("add a sticky filter bar to this page") with the skill available; confirm the description triggers it and the body changes what the agent checks (measures heights, tests both widths, guards touch hover). Iterate until it steers.
4. Symlink resolves and the skill appears in the skills list.
5. Add a one-line pointer to `MEMORY.md` and a memory note that the skill exists and what it covers.
