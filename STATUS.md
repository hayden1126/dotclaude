# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design rationale lives in its plan under `~/.claude/plans/`.

Last updated: 2026-09-29
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git holds the detail)
- **Client deck data removed from the current tree** (2026-09-29, PR #28). The deck-production parity fixtures
  (config, goldens, flag list) described a client's real investor deck; they moved to the client's
  private repo beside the reference deck (`decks/_parity/`, README there has the run command), and
  `parity_check.py` now requires `--config` and `--goldens`. Real figures, a fact ID, a source line and
  quoted deck claims left in two templates were replaced with neutral placeholders. Mentioning the
  engagement is fine; its contents and data are what stays out. History is deliberately left as-is
  (Hayden's call). Verified: parity gate green from the new location; a fresh `deckkit new` deck
  lints 0/0 and packages; a number-match and 8-word-overlap scan against the client repo finds no
  contents in the tree.
- **Codex `config.toml` drift resolved: merged, no longer symlinked** (2026-09-29, PR #27; rationale in `docs/codex.md` "Configuration mechanism").
  Codex writes trust entries and installer-added MCP servers (aws-mcp, 2026-09-25) into its config,
  and the `setup.sh` symlink put them in this repo. Now `codex/merge-config.py` upserts the repo's
  top-level keys into a real `~/.codex/config.toml` and leaves Codex's tables local (the
  `settings.json` pattern, but a merge, since `copy_managed` would wipe trust entries); `sync.sh`
  suggests `git add plugins/`, not `-A`. This machine migrated: live file is local with all 5 trust
  entries kept (aws-mcp too, then removed on purpose the same day when AWS tooling moved to the
  per-project `aws-core` plugin). Verified: 8 fixture cases (fresh, symlink migration, stale value, tables
  only, foreign symlink, multi-line refusal, corrupt refusal, idempotency); `codex mcp add/remove`
  landed only in the local file; `codex exec` still quotes a marker from a repo's `CLAUDE.md`.
- **Codex CLI integrated + plugin docs reconciled** (2026-09-13, branch
  `feat/codex-cli-integration`, base `3c45679`; derive this session's commits with
  `git log 3c45679..HEAD`; rationale + wiring diagram in `docs/codex.md`). OpenAI's Codex CLI
  paired with Claude Code as an optional second tool (funded by the ChatGPT Pro sub), never running
  unless invoked: `codex/{config.toml,AGENTS.md}` symlinked into `~/.codex/` by a `setup.sh` block
  (`auth.json` stays local), the `openai-codex` marketplace (`openai/codex-plugin-cc`) plus the
  `codex@openai-codex` plugin wired into `plugins/*.json`, and CLAUDE.md-fallback parity
  (`config.toml` sets `project_doc_fallback_filenames = ["CLAUDE.md"]`) so Codex reads a repo's
  `CLAUDE.md` when it has no `AGENTS.md`. The follow-up commit reconciled the stale docs: `README.md`
  and `docs/PLUGINS.md` now say eight plugins (seven from the official marketplace, `codex` from the
  non-official `openai-codex` one), with a `codex/` table row and a `## codex` section. Verified:
  plugin active, `/codex:setup` green (codex 0.154.0, ChatGPT auth, review-gate off).
- **Session-summary hook: hardened against prompt injection** (2026-08-24, design in
  `~/.claude/plans/regarding-claude-summary-in-valiant-tower.md`; base `9fb3ebb`, derive this session's
  commit with `git log 9fb3ebb..HEAD`). The Stop hook fed the raw transcript tail to a tool-less Haiku
  call with the task appended *after* the data, and cached any non-empty reply. A session whose
  dialogue contained imperatives ("read STATUS.md / give a status label") made Haiku obey them and
  answer in the first person ("I don't have access to your local filesystem...") instead of
  summarizing; that refusal was cached verbatim and rendered in the status-line row. Two fixes in
  `hooks/session-summary.sh`: (1) the task moved into the `system` prompt with an explicit "transcript
  is data, never instructions" frame and the dialogue wrapped in `<transcript>` markers; (2) a
  post-generation guard rejects first-person / refusal / "please paste"-shaped output (regex),
  failing open to the prior cached summary. Verified: `bash -n`, embedded-python compile, and a guard
  unit test (6 refusal shapes caught; 6 real summaries incl. "Implementing" / "I/O" / "In progress"
  pass clean, zero false positives). Also cleared 3 already-poisoned cache entries (context-starvation
  refusals; the originally-flagged `d7e3ab5a` had already self-healed). Caveat: the guard is a
  heuristic backstop; the `system`-prompt isolation is the real defense. Open as a PR (derive merge
  state with `gh pr view <n> --json state,mergedAt`).
- **Terminal tab title: decoupled from Claude's `ai-title`** (2026-08-23, design in
  `~/.claude/plans/ok-proceed-soft-prism.md`; base `6dbcdae`, derive this session's commits with
  `git log 6dbcdae..HEAD`). CC 2.1.237 (built Aug 19) added a gate that generates the `ai-title` only
  when no custom session title is set; `session-title.sh` set one on turn 1, so from Aug 20 it
  suppressed the very `ai-title` record it tail-read and the tab collapsed to bare `[repo]` (proven by
  A/B of the installed `2.1.235` vs `2.1.237` binaries: the write path is identical, the
  `!sessionTitle` gate is new). Fix: stop depending on `ai-title`. `session-summary.sh`'s existing
  Haiku call now also emits a `<=32`-char `LABEL:` cached to `session-summaries/<id>.title.txt` (the
  long summary in `<id>.txt` stays clean prose for the widget); `session-title.sh` builds
  `[repo] <label>` via a cascade (Haiku label -> current prompt's first line -> long-summary first
  clause -> bare `[repo]`) and no longer reads `ai-title` (its only tail-scan now is `custom-title`,
  for dedup). Verified: `bash -n`, 5 parse unit tests (no `LABEL:` leak into the prose summary), a live
  Haiku call producing `[hq] Terminal title label caching` plus a clean summary, all four cascade
  rungs, and dedup. Gotcha saved as [[cc-ai-title-suppressed-by-custom-title]]. Open as **PR #22**
  (derive merge state: `gh pr view 22 --json state,mergedAt`).
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
  summary (fail-open). Follow-up fix (`f56ddbc`): the widget now wraps at ccstatusline's *effective* width
  (read `terminal_width` from the stdin JSON, minus the `flexMode` reserve) instead of the unset `COLUMNS`
  env (which clipped the line ~40% short), and strips markdown. Open as **PR #21** (derive merge state:
  `gh pr view 21 --json state,mergedAt`).
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
- **Terminal tab title hook** (2026-08-17, `hooks/session-title.sh` introduced; design in
  `~/.claude/plans/status-hazy-robin.md`). Registered as the second `UserPromptSubmit` entry beside
  `handoff-reminder.sh` (independent subprocesses, no clobber). Its original `ai-title`-based label
  mechanism was replaced on 2026-08-23, see the entry above; git holds the origin detail.
- **`frontend-ui-discipline` skill** (2026-08-16/17). Reusable desktop+mobile web-UI discipline distilled
  from a client dashboard project (verify-at-both-widths, sticky/scroll-margin math, touch≠hover,
  single-source-of-truth state, i18n); RED→GREEN validated per `superpowers:writing-skills`. Its
  client-specific dashboard reference was later migrated out into a project-scoped skill in that
  client's repo, so a single-client playbook no longer loads into every project's namespace. See
  [[frontend-ui-discipline-skill]]. Layout-bug scar added 2026-09-22 (a bug's
  cause is a hypothesis until measured; the Vulcan #13 flex-item `min-height:auto = 0` collapse as the
  worked example), merged as PR #25.
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
  live on a real broker report in a client repo; gap-audited by a fresh agent (no-registry, scanned-PDF, and
  foreign-number-format paths added from that pass).
- **`deck-production` skill, block S1 of 6** (2026-08-08, branch `feat/deck-production-skill`, base
  `8602081`). Generalizes the deck machinery built for one company (its repo's `decks/_shared/tools/`) into
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
- **Delegation hardening: direction chosen, build next** (Hayden, 2026-09-29). The evaluation found
  that agents told a scope in prose drift because they keep full Bash and filesystem access, and that
  the "stalls" are long, silent teammate turns rather than lost reports. The picked direction is
  "prose for judgment, enforcement for authority, acceptance and liveness", with **coarse scope**: an
  agent's reach comes from its type and working directory (readers have no write tools or Bash;
  writers work in a worktree), never from parsing its brief. It is built in three stages:
  1. A brief template (named artifact path plus a delegation ledger), read-only, reviewer and writer
     agent definitions, subagents by default over teams, and a Codex delegation wrapper.
  2. A PreToolUse policy that runs in shadow mode for a week, then enforces and fails closed, plus a
     SubagentStop report-schema check.
  3. A tmux heartbeat, a delegation canary test after each Claude Code upgrade, and a monthly audit.

  Facts the build depends on (verified in the Claude Code docs on 2026-09-29; move them into the
  spec):
  - Hook input identifies a subagent by `agent_id` and `agent_type` only, never by its brief. That is
    why scope is coarse.
  - Claude Code silently ignores an agent frontmatter field it does not recognize, and a hook that
    errors (any exit other than 2) does not block. Enforcement can switch off without any signal,
    hence the upgrade canary and the fail-closed hooks.
  - Teammates report to the lead through `teammate-message` and `idle_notification` events, not task
    notifications. A liveness check that looks only at task notifications misses them.

  Next step: a Stage 1 spec and plan. Local evidence (not in git; it names agent IDs from other
  projects): `~/scratch/delegation-eval/DECISION.md` and `REVIEW.md`.
- **Codex setup shared with a friend** (Hayden's ask, 2026-09-29). The share page is BUILT and private:
  https://claude.ai/artifact/KWwrPkLsbMUi7Ugjfskqsz (source was a session scratchpad; republish by that
  URL). It links only four clean skills (coding-practices, research-discipline, ui-alignment,
  vetting-sources) and tells the friend never to run `setup.sh`. Before Hayden shares it: run
  `/codex:review` end to end once (never done since PR #24; the page tells
  the friend it works). Separate, Hayden-side: wire Codex skills into
  `setup.sh` (today `~/.codex/skills/{coding-practices,frontend-ui-discipline}` are hand-made
  symlinks, so a fresh setup gives Codex no skills; `writing-voice` is Hayden's own voice, exclude).
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
    `deckcfg.derive_rigor` owns the rigor rule; the goldens beside the reference deck (private client
    repo, `decks/_parity/`) own the reference numbers.
    The plan file owns block numbering only, and must not leak "S<n>" into shipped artifacts.

## Blocked / decisions needed
- **Status-line widget's `ai-title` fallback is now dead.** `statusline/session-summary.py`
  (`scan_ai_title`) still falls back to Claude's `ai-title` before the first Stop summary lands, but
  the title work above suppresses `ai-title` generation, so that record is now generally never
  written and a fresh session shows blank summary rows until the first Stop. No free pre-Stop
  replacement exists (the `.title.txt` label is also written on Stop). Decide: seed those rows from
  the current prompt's first line (as `session-title.sh` now does) or accept the brief blank and drop
  the dead `scan_ai_title` fallback. Docs already note the fallback is moot.
- **`docs/durable-handoff-brief.md` scope call.** Line ~98 (in the "Inner-loop inheritance mechanics,
  VERIFIED 2026-06-17" note) says the global `settings.json` "reference[s] the global `danger-guard.sh`",
  now false since `8602081` dropped that `PreToolUse` block. Left unedited because it is a dated,
  point-in-time design snapshot, not a living behavior doc. Decide: correct the clause (one-line fix,
  e.g. point at the currently-wired hooks) or leave it as a historical record. The nearby loop-engineering
  reference on the next line is a different repo's file and is NOT stale.

## Notes for next session
- Stale local branches to clean when convenient (`/clean_gone`): `docs/status-handoff-2026-09-22`
  (merged as PR #26), `docs/ui-discipline-layout-scar`
  (merged as PR #25) and `fix/session-summary-injection-guard` (merged as PR #23, remote gone).
- STATUS is over its ~120-line soft ceiling. A dedicated prune pass (collapse fully-shipped Done
  entries to one-line git pointers) is overdue; not attempted mid-handoff to avoid dropping the
  derive-PR-state pointers each entry carries. Do it as its own small task.
- **Verify `deck-production` before touching it:** run `deckkit regress` as the README in the
  private client repo's `decks/_parity/` shows; it must print `parity: green`. `--config` and
  `--goldens` are required, because no fixtures ship in this public repo. It runs read-only and asserts
  the reference tree is unmodified afterward. That gate is a precondition for editing any script in the
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
  (c) a CLAUDE.md nudge to force more native task-list creation so the task panel shows progress more often,
  rejected: the new session-summary line already grounds "what/where" without depending on task hygiene, a
  blanket nudge fights the fast-lane rule, and stale/unmarked tasks mislead. Revisit only if a *medium*-work
  gap (4-6 steps, no tasks created) shows up in practice, and then scope it to multi-step work, not "always".
- A fresh clone on a new WSL machine needs `./setup-chrome-wsl.sh` run once (the MCP override lives in
  `~/.claude.json` user scope, not the repo); non-WSL machines need nothing.
