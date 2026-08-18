# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design rationale lives in its plan under `~/.claude/plans/`.

Last updated: 2026-08-18
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git holds the detail)
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
  `CLAUDE.md` > skills precedence conflict that made G3 read as forbidden. Design + full sourced research in
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
- **`frontend-ui-discipline` trimmed to general-only** (2026-08-17). Its bella-specific
  `references/self-contained-dashboards.md` was **migrated out** into a new project-scoped `bella-dashboard`
  skill that now lives in the **bella repo** (`~/code/bella/.claude/skills/bella-dashboard/`, committed
  there, not here) — so a bella-only playbook no longer loads into every project's namespace. This repo's
  change: dropped the reference file, trimmed the SKILL.md intro line + the description's
  "self-contained-dashboard specifics" tail, and added a migration note atop `SPEC.md`. The new skill also
  captured the streaming-chat + Worker-backend + CJK-typography scars from post-2026-08-16 bella work. See
  [[frontend-ui-discipline-skill]], [[bella-dashboard-skill]].
- **Handoff: proactive CLAUDE.md trigger** (2026-08-16, branch `handoff-proactive-claude-md`, commit
  `6c775d8`). `skills/handoff/SKILL.md` Step 2 now fires one narrow, prune-biased proactive CLAUDE.md
  reflection (a durable repo-level convention/structural fact established this session → propose via
  `/revise-claude-md`, scoped to that fact), tells the reconcile sub-agent to cover nested CLAUDE.md
  files (not just root), and gains a Common Mistakes row for the silent-omission case. Design rationale
  in `~/.claude/plans/improve-my-handoff-skill-inherited-lamport.md`. See [[dotclaude-handoff-skill]].
- **`frontend-ui-discipline` skill** (2026-08-16). Reusable web-UI discipline (desktop + mobile) distilled
  from the Bella president-dashboard UI work: `SKILL.md` (themed sections — verify-at-both-widths, measure-
  don't-assume, sticky/scroll-margin offset math, touch≠hover, single-source-of-truth state, overlays /
  highlight / i18n, robustness, responsive) + (originally) a `references/self-contained-dashboards.md`
  bella pattern reference, **migrated out to the bella repo on 2026-08-17 — see the entry above**.
  Authored from its own `SPEC.md` (kept in the
  dir as source), a third `~/bella/dashboards/president-briefing/build.py` rationale pass, and a full-history
  sweep of all 51 Bella commit messages. **RED→GREEN validated** per `superpowers:writing-skills`: a
  skill-less agent missed 16px inputs / 44px tap-targets / measured sticky offset; the same task with the
  skill fixed all three. Symlinked into `~/.claude/skills`. SKILL.md ~800 words (over the ~500 soft target,
  kept for coverage; split lever = move the two low-frequency sections into a second reference). See
  [[frontend-ui-discipline-skill]].
- **`vetting-sources` skill** (2026-08-15, commit `245eeda`). New procedural skill: bring an external /
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
- (none currently)

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
  already inherits there); (b) cross-platform notifiers for the toast (YAGNI on this WSL-only setup).
- A fresh clone on a new WSL machine needs `./setup-chrome-wsl.sh` run once (the MCP override lives in
  `~/.claude.json` user scope, not the repo); non-WSL machines need nothing.
