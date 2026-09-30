# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design rationale lives in its plan under `~/.claude/plans/`.

Last updated: 2026-09-30
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git, the linked plans and memory hold the detail)
- **Machine overlay, installed on HAYPC** (2026-09-30, PR #40). A machine's own settings live in
  `~/.claude/settings.machine.json` (README, "Quickstart"); HAYPC's holds hq's `hq-* *` exclusions and
  the `tmux-state.sh` hooks. The sandbox stub block and `stop-ring.sh` now ship from this repo.
- **Delegation hardening Stage 2 built and installed on HAYPC** (2026-09-30, PRs #35 to #38, merged
  range `e536dd8..b4a85ae`). It covers the session-wide sandbox, the subagent policy hook, report-check,
  `gh-public`, and the ledger's `audit` and `sandbox-denials`. `docs/delegation.md` holds the design,
  the verified facts, the known gaps and the install order. Sandbox behavior on this machine is in
  memory [[cc-sandbox-linux-facts]].
- **Client deck data removed from the current tree** (2026-09-29, PR #28). Parity fixtures live in the
  client's private repo (`decks/_parity/`); `parity_check.py` requires `--config` and `--goldens`.
  History deliberately left as-is (Hayden's call).
- **Codex `config.toml` merged, not symlinked** (2026-09-29, PR #27; rationale in `docs/codex.md`,
  "Configuration mechanism").
- **Codex CLI integrated** (2026-09-13, `feat/codex-cli-integration`; wiring and rationale in
  `docs/codex.md`).
- **Session-summary hook hardened against prompt injection** (2026-08-24, base `9fb3ebb`; design in
  `~/.claude/plans/regarding-claude-summary-in-valiant-tower.md`). The `system`-prompt isolation is the
  real defense; the refusal-shape regex is a backstop.
- **Terminal tab title decoupled from `ai-title`** (2026-08-23, PR #22; design in
  `~/.claude/plans/ok-proceed-soft-prism.md`; gotcha [[cc-ai-title-suppressed-by-custom-title]]).
- **Session-summary status-line row** (2026-08-18, PR #21; design in
  `~/.claude/plans/in-an-earlier-session-toasty-marshmallow.md`). Caveat: the OAuth credentials file it
  reads is undocumented and its token rotates; a failed read keeps the last summary.
- **Loose decisions resolved** (2026-08-18, PR #20; design in `~/.claude/plans/status-enumerated-kitten.md`):
  danger-guard ships but is opt-in; the CLAUDE.md parallel-edits carve-out.
- **Terminal tab title hook** (2026-08-17; design in `~/.claude/plans/status-hazy-robin.md`).
- **`frontend-ui-discipline` skill** (2026-08-16/17; layout-bug scar merged as PR #25;
  [[frontend-ui-discipline-skill]]).
- **Handoff: proactive CLAUDE.md trigger** (2026-08-16, `6c775d8`; [[dotclaude-handoff-skill]]).
- **`vetting-sources` skill** (2026-08-15, `245eeda`).
- **`deck-production` block S1 of 6** (2026-08-08, base `8602081`; S1-S6 plan in
  `~/.claude/plans/explore-our-entire-workflow-bright-shamir.md`).
- Older (git and memory hold the detail): ctx chip percent (PR #12 follow-up), handoff-lifecycle
  hardening (`4df5a49..af14b97`), WSL2 `chrome-devtools-mcp` (PR #13, [[dotclaude-chrome-devtools-wsl]]),
  research-sourcing (PR #10), staged-reader-review upgrade, danger-guard opt-in auto mode.

## In flight
- **Delegation hardening: Stage 2 live; Stage 3 (upgrade canary) is next** (`docs/delegation.md`,
  "Next"). `skills/delegation/SKILL.md` is the operating guide. Open items:
  - **After 2026-10-07:** run `delegation-ledger sandbox-denials --days 7` and add the hosts that were
    actually needed to `sandbox.network.allowedDomains`.
  - **Not observed live:** a real agent's `dangerouslyDisableSandbox` being denied. The teammate probe
    declined to try it; the harness covers the rule (37/37).
  - **Other machines:** install by hand per the docs' install order (the policy hook fails closed).
    bubblewrap and socat are required.
  - **Optional:** a no-scope classic GitHub token at `~/.config/dotclaude/github-public-token` enables
    `gh-public` code search.
  - **Write-up:** Hayden wants a blog post or public repo on the findings. The evidence (probe
    settings, prompts and outputs, harness logs) is in `~/scratch/delegation-writeup/evidence/`, and
    the older eval is in `~/scratch/delegation-eval/`. Raw transcripts embed private context, so
    never publish them as-is.
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
  now false since `8602081` dropped the danger-guard `PreToolUse(Bash)` entry. Left unedited because it is a dated,
  point-in-time design snapshot, not a living behavior doc. Decide: correct the clause (one-line fix,
  e.g. point at the currently-wired hooks) or leave it as a historical record. The nearby loop-engineering
  reference on the next line is a different repo's file and is NOT stale. The same doc's lines ~49-50
  ("setup.sh symlinks its skills, the danger-guard hook, CLAUDE.md, and templates") are also stale
  now (setup.sh links every hook, `agents/`, and the CLIs). Include them in the same call.
- **Historical docs naming `Explore` for git work.** `skills/frontend-ui-discipline/SPEC.md:14` (an
  authoring record) tells an Explore agent to read a diff of the session's commits. The `Explore`
  override has no shell, so that step now needs `researcher` or a pasted diff. Decide: update the
  record, or leave it as history.

## Notes for next session
- **Verify delegation before touching it:** `python3 -m unittest discover -s tests/delegation -t tests/delegation`
  (138 tests, no model calls; they pass inside the sandbox too), and the installer helpers with
  `python3 -m unittest discover -s tests/setup -t tests/setup`. The live harness `tests/delegation/run.py --runner claude|codex` spends
  model calls. Run it after changing a role, a hook or `codex-delegate`, and after a Claude Code upgrade
  until the Stage 3 canary exists.
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
