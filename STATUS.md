# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design rationale lives in its plan under `~/.claude/plans/`.

Last updated: 2026-08-18
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git holds the detail)
- **Session-summary status-line row** (2026-08-18, design in
  `~/.claude/plans/in-an-earlier-session-toasty-marshmallow.md`). A persistent 1-2 sentence "what is this
  session doing, and where does it stand" line so several concurrent Claude terminals are tellable apart
  without relying on the (often off-screen) native task panel. Two decoupled halves:
  **`statusline/session-summary.py`**, a ccstatusline custom-command widget on the previously-empty lines 2-3
  (`--row 1`/`--row 2`, dim, word-wrapped to COLUMNS) that reads a cached summary and falls back to the
  transcript's `ai-title`; and **`hooks/session-summary.sh`**, a `Stop` hook that regenerates the summary via a
  **direct Haiku Messages-API call authenticated with the Claude subscription OAuth token** from
  `~/.claude/.credentials.json` (no API key; stdlib `urllib`, no jq), writing
  `<config-dir>/session-summaries/<session_id>.txt`. Detached (never blocks the turn), fail-open, cadence-gated
  (skips if the transcript grew <2KB), feeds the prior summary back. Chosen over headless `claude -p` after
  measuring both live: direct API ~3.7s and ~3x cheaper (no system-prompt overhead) vs `claude -p` ~11.7s.
  `setup.sh` §5 generalized: symlinks BOTH `statusline/*.py`, patches any custom-command commandPath preserving
  trailing args, and idempotently grafts the two widgets into an existing install. `settings.json` registers the
  Stop hook, but it is COPIED by setup.sh (needs a `./setup.sh` re-run or hand-edit). This session installed
  **surgically** (live ccstatusline config patched + hook appended to live `settings.json`) because a full
  `copy_managed` would clobber the runtime-managed `model` key; the widget is live now, the Stop-hook
  auto-refresh activates next session. **Line 1 (metrics/ctx) left untouched** so the loop-engineering
  input-ready detector is unaffected. Verified: widget unit-tested (wrap/fallback/empty), the real ccstatusline
  binary renders 3 lines and collapses empty rows, and a live OAuth call produced accurate summaries. Caveat:
  the OAuth credentials file is undocumented and its token rotates; a stale/failed read just leaves the last
  summary (fail-open). Open as **PR #21** (derive merge state: `gh pr view 21 --json state,mergedAt`).
- **Two loose decisions resolved** (2026-08-18, branch `feat/resolve-loose-decisions`). (a) **danger-guard
  README fix** (`bb99b31`): the Hooks section listed `PreToolUse(Bash): danger-guard.sh` as wired, but
  `settings.json` intentionally omits it (dropped in `8602081`). Reframed as ships-but-opt-in with the
  opt-in path spelled out; no `settings.json` change (kept opt-in by default per Hayden, who runs it off
  locally). (b) **parallel-edits carve-out** (`d035a7e`, via `/revise-claude-md`): CLAUDE.md line 23's flat
  "never parallel edits" is now conditional (parallel edits only when each agent writes its own new file no
  other agent touches + single-threaded merge; never same file / shared state). Backed by a 5-agent sourced
  research sweep (Karpathy, Anthropic multi-agent guidance, the worktree-parallel camp, and the serial camp
  all converge on that same boundary) and by Hayden's own skills already encoding the disjoint-file
  qualifier (deck-production G3, frontend-ui-discipline, vetting-sources, research-sourcing); resolves the
  `CLAUDE.md` > skills precedence conflict that made G3 read as forbidden. (c) The handoff reconcile pass
  also fixed stale "danger-guard active by default" claims in `skills/handoff/SKILL.md` and `setup.sh`
  (`a0b8ada`); one incidental now-false clause in `docs/durable-handoff-brief.md` (a dated VERIFIED
  snapshot) was left for a scope call, see Blocked. Open as **PR #20** (derive merge state:
  `gh pr view 20 --json state,mergedAt`). Design + full sourced research in
  `~/.claude/plans/status-enumerated-kitten.md`.
- **Terminal tab title hook** (2026-08-17). New `hooks/session-title.sh` (UserPromptSubmit) sets the
  session title (== terminal tab title) to `[<repo>] <ai-summary>` via the supported
  `hookSpecificOutput.sessionTitle` field (NOT raw OSC), so tabs are tellable apart while the
  running/idle status icons stay intact. Repo name from a pure-python `.git` walk (no subprocess,
  ~10ms); summary is the freshest `{"type":"ai-title",...}` line tail-read from the transcript
  (one-turn lag on a brand-new session; AI-title generation is not gated by a custom title, so it
  stays live). Registered as the second `UserPromptSubmit` entry alongside `handoff-reminder.sh`;
  both run as independent subprocesses and Claude Code aggregates their outputs (additionalContext
  accumulates, sessionTitle applied separately), so no clobber. Mechanism reverse-engineered from the
  installed binary (v2.1.233): tab title = session name, precedence `customTitle ?? aiTitle`,
  `terminalTitleFromRename` defaults true so no settings toggle is needed. Format/branch/turn-1
  fallback are tunables at the top of the script. NOTE: `settings.json` is COPIED by setup.sh, so the
  registration needs a `./setup.sh` re-run or a `~/.claude/settings.json` hand-edit (both done this
  session; the running session even picked the new registration up live, no restart). Fail-open;
  needs python3. Verified end-to-end: Stage-1 battery green (12/12), and the hook fired live this
  session (6 `custom-title` lines, tab set to `[dotclaude] <summary>`), with dedup (key `customTitle`,
  confirmed on live data) suppressing redundant re-emits when the summary is unchanged. Design in
  `~/.claude/plans/status-hazy-robin.md`.
- **`frontend-ui-discipline` skill** (2026-08-16/17). Reusable desktop+mobile web-UI discipline distilled
  from the Bella dashboard work (verify-at-both-widths, sticky/scroll-margin math, touch≠hover,
  single-source-of-truth state, i18n); RED→GREEN validated per `superpowers:writing-skills`. Its
  bella-specific dashboard reference was later migrated out into a project-scoped `bella-dashboard` skill in
  the bella repo, so a bella-only playbook no longer loads into every project's namespace. See
  [[frontend-ui-discipline-skill]], [[bella-dashboard-skill]].
- **Handoff: proactive CLAUDE.md trigger** (2026-08-16, branch `handoff-proactive-claude-md`, commit
  `6c775d8`). `skills/handoff/SKILL.md` Step 2 now fires one narrow, prune-biased proactive CLAUDE.md
  reflection (a durable repo-level convention/structural fact established this session → propose via
  `/revise-claude-md`, scoped to that fact), tells the reconcile sub-agent to cover nested CLAUDE.md
  files (not just root), and gains a Common Mistakes row for the silent-omission case. Design rationale
  in `~/.claude/plans/improve-my-handoff-skill-inherited-lamport.md`. See [[dotclaude-handoff-skill]].- **`vetting-sources` skill** (2026-08-15, commit `245eeda`). New procedural skill: bring an external /
  third-party document into a knowledge base by faithful multi-agent extraction, an accuracy + internal-
  consistency audit (reconcile vs filings and the web, then adversarially verify), and a cite-safety
  brief; quarantine holds until the audit clears. Delegates to `research-sourcing` / `research-discipline`
  / `writing-voice` / `staged-reader-review` / `ebook-extract` / `dispatching-parallel-agents`; ships
  `references/workflow-scaffolds.md` with the reusable Workflow skeletons. Built while running the pipeline
  live on a real broker report in `~/bella`; gap-audited by a fresh agent (no-registry, scanned-PDF, and
  foreign-number-format paths added from that pass).
- **`deck-production` skill, block S1 of 6** (2026-08-08, branch `feat/deck-production-skill`, base
  `8602081`). Generalizes the deck machinery built for one company (`~/bella/decks/_shared/tools/`) into
  config-driven tooling: `deckkit` dispatcher (its main job is picking the interpreter), `deckcfg`
  (tomllib, CLI > env > file > default), scaffolder, and generalized build/lint/package plus serve,
  doctor, and the reference-deck regression gate. Templates carry the storyboard grammar, builder
  contract, substrate trio, and review-record format. Design and the S1-S6 block plan live in
  `~/.claude/plans/explore-our-entire-workflow-bright-shamir.md` (gitignored, machine-local).
- **Status-line ctx chip: percent + divider** (2026-07-11, follow-up to PR #12).
  `statusline/ctx-breakdown.py` total chip renders its share of the auto-compact window as a percent,
  set off from the per-category chips by a dim `▏`. Derive PR/merge state with `gh pr list`.
- **Handoff-lifecycle hardening** (2026-07-11, `4df5a49..af14b97`). `skills/handoff/SKILL.md` enforces
  prune-as-you-write and "volatile git state: derive, never store"; `hooks/handoff-reminder.sh` rewritten
  precision-first (23-case battery); `CLAUDE.md` gained the read-side resume line. See
  [[dotclaude-handoff-skill]].
- **WSL2 `chrome-devtools-mcp` fix (opt-in)** (2026-07-10, PR #13). `setup-chrome-wsl.sh` +
  `docs/chrome-devtools-wsl.md` + `chrome-debug.ps1`. Confirmed live and working 2026-08-08. See
  [[dotclaude-chrome-devtools-wsl]].
- Prior shipped (git + memory hold detail): research-sourcing skill (PR #10), staged-reader-review
  bundle upgrade, danger-guard opt-in auto mode, statusline ctx chips (PR #12).

## In flight
- **`deck-production` blocks S2-S6.** S1 shipped and verified; the skill has the phase model and the core
  loop but no orchestration layer, so an agent cannot yet run a deck end to end.
  - **Next concrete step: block S3, the geometry gate** (`geometry.py` + `geometry_probe.js` + a
    declarative `geometry.rules.toml`), because it catches the defect class screenshots miss. Its
    verification target is sharp and already specified: the gate must FAIL on a fixture reproducing the
    reference deck's s17 overlap defect (unbounded caption `max-width`, no panel background, anchors
    ~95px apart) and PASS on the real s17 as it stands today.
  - Then S2 (fonts + PDF), S4 (SKILL references + 6 Workflow scripts), S5 (ingest + theme extractor),
    S6 (pptx export). S1-S4 is the usable product.
  - Ownership rule established this block: SKILL.md owns the phase model, gates, and batch constants;
    `deckkit`'s `COMMANDS` dict owns the CLI surface (help is generated, never transcribed);
    `deckcfg.derive_rigor` owns the rigor rule; `tests/parity/goldens.json` owns the reference numbers.
    The plan file owns block numbering only, and must not leak "S<n>" into shipped artifacts.

## Blocked / decisions needed
- **`docs/durable-handoff-brief.md` scope call.** Line ~98 (in the "Inner-loop inheritance mechanics,
  VERIFIED 2026-06-17" note) says the global `settings.json` "reference[s] the global `danger-guard.sh`",
  now false since `8602081` dropped that `PreToolUse` block. Left unedited because it is a dated,
  point-in-time design snapshot, not a living behavior doc. Decide: correct the clause (one-line fix,
  e.g. point at the currently-wired hooks) or leave it as a historical record. The nearby loop-engineering
  reference on the next line is a different repo's file and is NOT stale.

## Notes for next session
- **Verify `deck-production` before touching it:** `deckkit regress --ref-deck
  ~/bella/decks/2026-07-general-en` must print `parity: green`. It runs read-only and asserts the
  reference tree is unmodified afterward. That gate is a precondition for editing any script in the
  skill, because the reference deck is deliberately NOT migrated and will otherwise drift silently.
- Smoke test: `deckkit new /tmp/x --title T --slides 6`, approve the storyboard frontmatter, then
  `deckkit build /tmp/x && deckkit lint /tmp/x && deckkit package /tmp/x`. Expect lint 0/0.
- `deckkit` reaches PATH via `~/.local/bin` (setup.sh links it when that dir exists). On a machine
  without it, use `~/.claude/skills/deck-production/scripts/deckkit`.
- Known gap carried deliberately: `deck.forward_targets` is declared in `deck.toml`, not detected. No
  tooling yet reads a slide and decides whether a number is a forward target, so the default `false`
  means "nobody has said", not "no targets". Revisit when the storyboard MUST/NEVER grammar is enforced
  in S3.
- research-sourcing follow-ups (all optional): the thorough-tier planted-fabrication spot-check is
  specified but never exercised end to end; only tested with Agent-tool subagents, not a real
  Workflow-tool run.
- Deferred (also in [[dotclaude-handoff-skill]]): (1) the deterministic PreCompact/Stop safety-net hook,
  revisit only after testing the `SessionStart` `compact`-matcher re-inject path (bug #15174); (2) the
  autonomous loop-engineering handoff (a Python orchestrator step that refreshes the RESUME block).
- Evaluated and SKIPPED, do not re-raise: (a) wiring `handoff-reminder.sh` into the loop-engineering inner
  loop (the puppet gets one machine prompt with no wrap-up phrase, so the hook has no addressee; the skill
  already inherits there); (b) cross-platform notifiers for the toast (YAGNI on this WSL-only setup);
  (c) a CLAUDE.md nudge to force more native task-list creation so the task panel shows progress more often
  — rejected: the new session-summary line already grounds "what/where" without depending on task hygiene, a
  blanket nudge fights the fast-lane rule, and stale/unmarked tasks mislead. Revisit only if a *medium*-work
  gap (4-6 steps, no tasks created) shows up in practice, and then scope it to multi-step work, not "always".
- A fresh clone on a new WSL machine needs `./setup-chrome-wsl.sh` run once (the MCP override lives in
  `~/.claude.json` user scope, not the repo); non-WSL machines need nothing.
