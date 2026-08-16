# Self-contained dashboards

The specific pattern behind the Bella president-briefing dashboard: one build script emits one self-contained HTML file with zero external requests, served behind an auth gate. Read this when building a gated, single-file dashboard with traceable facts and provenance. The general craft lives in the parent `SKILL.md`; this is the pattern and its bug catalogue.

## The build

- **One build script → one self-contained HTML.** `build.py` reads `content.json` and emits HTML via f-strings; CSS is one `r"""..."""` constant, JS another; fonts are base64 `@font-face` data URIs. Zero external requests, so no side-loaded asset can escape the auth gate.
- **Build-time audience segregation, not a client toggle.** `build(internal, sibling)` filters `content.json` by `audience` at build time, so the investor file physically contains zero internal strings. A client-side show/hide would leak confidential facts via view-source. One builder, two data sets, two files. Verify no-leak with `grep` on the built investor file.
- **Sticky offsets cascade in pure CSS.** The internal build's conditional confidential banner shifts every downstream sticky `top` via the `~` sibling combinator (`.confidential ~ .layout .sidebar{top:31px}`, `.confidential ~ .layout .reg thead th{top:31px}`), so the investor build (no banner) needs no different rules and no JS.

## Facts, IDs, provenance

- **Every number traces to an `F-NNN` id.** A `.prov` overlay reveals source/F-ID on hover/tap/focus; a full registry table lists all facts with source chips.
- **Cross-links both ways.** F-ID → `#reg-<fid>` registry row (rows carry that id, land with a `:target` highlight); registry Section cell → `#<section>`.
- **F-IDs are plumbing, not reading material.** Surfaced on demand via the overlay where they compete with the number; kept always-on only in the registry (the lookup table).

## i18n mechanism

- **`_zh` sibling keys** in `content.json` (`claim_zh`, etc.); `t()` / `bi()` / `bi_field()` helpers for HTML, `bi_svg()` for SVG `<text>` labels so chart text translates through the identical toggle path.
- **CJK falls through to system fonts.** The base64 IBM Plex subset is Latin-only, so every font stack appends a system CJK fallback var (`--cjk: PingFang SC, Microsoft YaHei, …`); Chinese renders from the OS while Latin stays pixel-identical (embedding a CJK webfont is multi-MB). General i18n rules are in the parent skill.

## Deploy contract

From `dashboards/president-briefing/DEPLOYMENT.md`:

- **Build first, then deploy.** `.venv/bin/python dashboards/president-briefing/build.py` — `cd /home/hayden/code/bella` first, the shell cwd resets between tool calls. Then deploy from the dashboard dir with `npm run deploy` (wrangler). The build is **not** wired into the npm script; run it yourself or you deploy stale HTML.
- **Only `site/` deploys.**
- **Cloudflare Access is scoped to the `/internal` path**, not the whole subdomain (unlike the sibling Capella project).
- **The `*.hayden1126.dev` wildcard cert is used deliberately** so the "bella" hostname never appears in certificate-transparency logs.
- **One-time-PIN auth only** (other IdPs off): the target user is on a Yahoo address, and OTP mails a code to any address.
- Live-verify after deploy: `/` → 200, gated path → 302, and `curl -s --compressed` the served HTML and `grep` for the new markup (Cloudflare serves gzip; without `--compressed` the page looks empty even when live).

Cross-ref memory `[[bella-president-dashboard-deployed]]`.

## Bug catalogue

The scars from building this. Each row is a rule with a story, which is why it sticks.

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
