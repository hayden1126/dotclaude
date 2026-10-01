# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design rationale lives in its plan under `~/.claude/plans/`.

Last updated: 2026-10-01
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git, the linked plans and memory hold the detail)
- **Delegation hardening Stage 3: Step 0, A0, A4, A5, A1 and A3, live on HAYPC** (2026-09-30
  to 10-01; PRs #42 to #46, range `d46449b..ce16b8a`; A1 is PR #48, range `c0a3241..1d09748`;
  A3 is PR #49, range `1d09748..65e7297`).
  - Named spawns are denied unless their name starts with `team-`.
  - Teammates are policed by their role (meta.json `customAgentType`).
  - `delegation-ledger canary` re-verifies enforcement. A SessionStart hook runs the cheap checks
    and shows a line only when something is due; `delegation-ledger due` shows the last results.
  - A1: `open` reads liveness from the agent transcript (`in Bash 12 min`, with a `⚠` past the
    thresholds in `liveness.toml`). The ledger hook keeps a per-agent index for A2.
  - A3: `delegation-ledger watch` lists the live delegations, and `--summary` puts a token
    (`2▶ 1⚠`) in the tmux bar through the machine-local `~/bin/tmux-claude-status`. The sandbox
    hides every session pid, so `delegation-ledger *` is in `excludedCommands`.

  `docs/delegation.md` "Stage 3" holds the findings, the decisions and the test counts.
- Older (git, the PRs and memory hold the detail): `setup.sh` keeps the live settings' own keys
  (PR #47, [[dotclaude-setup-install-model]]), the machine overlay `settings.machine.json`
  (PR #40, README "Quickstart"), delegation Stage 2 (PRs #35 to #38, `docs/delegation.md`,
  [[cc-sandbox-linux-facts]]), client deck data removed from the tree (PR #28;
  history deliberately left as-is, Hayden's call), Codex `config.toml` merged, not symlinked (PR #27)
  and the Codex CLI integration (both in `docs/codex.md`), session-summary prompt-injection hardening
  (2026-08-24), tab title decoupled from `ai-title` (PR #22,
  [[cc-ai-title-suppressed-by-custom-title]]), the session-summary status-line row (PR #21,
  [[dotclaude-session-summary-statusline]]), loose decisions (PR #20: danger-guard opt-in, the
  parallel-edits carve-out), the tab title hook, `frontend-ui-discipline` (PR #25), the handoff
  CLAUDE.md trigger, `vetting-sources`, `deck-production` S1, and earlier work back to PR #10.

## In flight
- **Delegation hardening Stage 3: A2 (deadline: nudge, then hard stop) is built** on branch
  `feat/delegation-a2-deadline`, not yet merged; then A6.
  - **The plan:** `~/.claude/plans/deep-moseying-koala.md`. Step 0 (the probes) and Step 1 (the
    build) are done; Step 2 is left:
    - review the branch, then run both unit suites outside the sandbox (270 tests expected);
    - run the live case, `python3 tests/delegation/run.py --runner claude --cases deadline`,
      from the worktree, outside the sandbox, then fill the "A2, 2.1.287" results block in
      `docs/delegation.md` "Tests";
    - after Hayden approves the PR and the merge, `./setup.sh` (copy `~/.claude/settings.json`
      first and diff it after), then `delegation-ledger canary` in the background. It must go
      green on 2.1.287 with more than 56 checks, and `delegation-ledger due` should then be
      quiet apart from the dated 2026-10-07 item.
  - Build each step on a fresh branch from `main` in a worktree, so the live hooks stay
    untouched while it is edited.
  - **The plans:** Stage 3 is `~/.claude/plans/lets-move-on-to-refactored-pascal.md`.
    - Its A1 and A3 text is detailed in `~/.claude/plans/woolly-jingling-cookie.md`, which holds
      both plans, A3 first.
    - Its A4/A5 cadence is in `docs/delegation.md` ("The canary and the due checks").
    - A2's decisions and why are in `docs/delegation.md` "Deadline (A2)". A6 retunes its
      budgets against the ledger.
- **Delegation hardening: what is live on HAYPC** (Stage 2, plus the Stage 3 steps under Done;
  `docs/delegation.md`;
  `skills/delegation/SKILL.md` is the operating guide). Open items:
  - **Other machines:** `git pull` in `~/dotclaude`, then `./setup.sh`, both outside the sandbox
    (A4 and A3 changed `settings.json`, and A2 adds a PostToolUse hook to it).
    - A baseline key still wins over the live file's value, so copy `~/.claude/settings.json`
      first and diff it after.
    - Without a `settings.machine.json` overlay, install by hand per the docs' install order:
      the policy hook fails closed.
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
- **`deck-production` blocks S2-S6** (plan: `~/.claude/plans/explore-our-entire-workflow-bright-shamir.md`).
  S1 shipped and verified (base `8602081`); the skill has the phase model and the core loop but no
  orchestration layer, so an agent cannot yet run a deck end to end.
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
- **Verify delegation before touching it:**
  `python3 -m unittest discover -s tests/delegation -t tests/delegation` and
  `python3 -m unittest discover -s tests/setup -t tests/setup` make no model calls. They pass inside
  the sandbox, except from a checkout under `.claude/worktrees/`, where the policy tests refuse and
  need the sandbox off. `delegation-ledger canary` runs them, then the live harness
  (`tests/delegation/run.py --runner claude`, which spends model calls), and records the result. Run
  it outside the sandbox, in the background, after changing a role, a hook or `codex-delegate`;
  after an upgrade, the session-start line says when. Counts and results live in
  `docs/delegation.md`, "Tests".
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
- Deferred handoff work (the PreCompact/Stop safety net, the loop-engineering handoff) is in
  [[dotclaude-handoff-skill]].
- Evaluated and SKIPPED, do not re-raise: (a) wiring `handoff-reminder.sh` into the loop-engineering
  inner loop (its one machine prompt has no wrap-up phrase, so the hook has no addressee); (b)
  cross-platform notifiers for the toast (YAGNI on WSL-only); (c) a CLAUDE.md nudge to create more
  native tasks (the session-summary line already grounds "what/where", and a blanket nudge fights the
  fast lane). Revisit (c) only if a 4-6 step job with no tasks shows up, scoped to multi-step work.
- A fresh WSL clone needs `./setup-chrome-wsl.sh` once ([[dotclaude-chrome-devtools-wsl]]).
