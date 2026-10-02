# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design rationale lives in its plan under `~/.claude/plans/`.

Last updated: 2026-10-01
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git, the linked plans and memory hold the detail)
- **Delegation hardening Stage 3: Step 0, A0, A4, A5, A1, A3 and A2, live on HAYPC** (2026-09-30
  to 10-01; PRs #42 to #46, range `d46449b..ce16b8a`; A1 is PR #48, range `c0a3241..1d09748`;
  A3 is PR #49, range `1d09748..65e7297`; A2 is PRs #51 and #52, range `0aa08f8..270dcb8`). Named spawns
  need a `team-` prefix; teammates are policed by role; `delegation-ledger canary`/`due`
  re-verify enforcement on their own; `open` and `watch` read liveness from the transcript, and
  `watch --summary` feeds the tmux bar. A2 nudges, then stops, an agent past its role's budget
  (`policy.toml` `[deadline]`).
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
- **Delegation hardening Stage 3: A6 (monthly audit), the last step, is PR #55** (range
  `e4b790a..feat/a6-monthly-audit`; state: `gh pr view 55 --json state,mergedAt`). It adds
  `delegation-ledger audit --monthly` (usage for retuning `[deadline]` and `liveness.toml`),
  `delegation-ledger exclude` (keeps probes out of those numbers), and a `due` nudge for the
  monthly run. Design and decisions: `~/.claude/plans/a6-jazzy-sloth.md` and `docs/delegation.md`
  "Monthly audit (A6)". After it merges:
  - `git pull` in `~/dotclaude`, outside the sandbox. A6 changes no `settings.json`, so
    `setup.sh` isn't needed: the CLI and the hooks are symlinks.
  - With Hayden's go-ahead, append the legacy exclusions on HAYPC, each as a bare command:
    `delegation-ledger exclude --id apolicy-check-50aa2e0cfe57efc9 --why probe`, the same for
    `ateam-probe-4965ec049f19323d` and `ateam-probe-2-d512254be0629b3d`, then
    `--id a572ffd9d3102036e --why "install check"` and
    `--session c9df7b29-0f66-4fc4-a932-253715942860 --name install-probe --why probe`.
    `poster-audit` stays in: it was real work.
  - Run `delegation-ledger canary --quick`, bare, so the merged code's quick tier is on record.
  - **Retune later, not now.** Once the ledger is a month old, `due` asks for `audit --monthly`
    (the date and the first sample sizes are in that docs section). Retune only the groups it
    doesn't mark `too few to retune`. The live ledger is real work, not harness: the harness
    writes to its own fixture state.
  - Then remove the worktree (`git worktree remove .claude/worktrees/a6`, outside the sandbox).
  - The "reports failing the contract: 3" in the daily audit is three known pre-fix rows from
    2026-09-30, gone from its window on 2026-10-07.
- **Delegation hardening: what is live on HAYPC** (Stage 2, plus the Stage 3 steps under Done;
  `docs/delegation.md`;
  `skills/delegation/SKILL.md` is the operating guide). Open items:
  - **Other machines:** `git pull` in `~/dotclaude`, then `./setup.sh`, both outside the sandbox
    (A4 and A3 changed `settings.json`, and A2 adds a PostToolUse hook to it; A6 changes none).
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
  vetting-sources) and tells the friend never to run `setup.sh`. It is ready to share
  (`/codex:review` ran end to end on 2026-10-01). Separate, Hayden-side: wire Codex skills into
  `setup.sh` (today `~/.codex/skills/{coding-practices,frontend-ui-discipline}` are hand-made
  symlinks, so a fresh setup gives Codex no skills; `writing-voice` is Hayden's own voice, exclude).
- **`deck-production` blocks S2-S6** (plan: `~/.claude/plans/explore-our-entire-workflow-bright-shamir.md`,
  missing from HAYPC's `~/.claude/plans/` on 2026-10-01; find it on the machine that wrote it, or
  rebuild it from this block).
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
- **Sandbox stubs slip past the managed git ignore.** `git/install-ignore.py` writes root-anchored
  patterns (`/x`) and leaves out `.mcp.json`. So `.mcp.json` shows as untracked, and a Bash
  command run from a subdirectory gets its own `/dev/null` mounts there (`tests/.mcp.json`,
  `tests/delegation/.claude/*`), which `git add -A` then trips on. Workaround: `git add -u`, and
  run Bash from the repo root. Decide: add `/.mcp.json` to the list (cheap), and whether to
  unanchor the patterns, which would also hide real nested files with those names.
- **Status-line widget's `ai-title` fallback is now dead.** `statusline/session-summary.py`
  (`scan_ai_title`) still falls back to Claude's `ai-title` before the first Stop summary lands, but
  the title work above suppresses `ai-title` generation, so that record is now generally never
  written and a fresh session shows blank summary rows until the first Stop. No free pre-Stop
  replacement exists (the `.title.txt` label is also written on Stop). Decide: seed those rows from
  the current prompt's first line (as `session-title.sh` now does) or accept the brief blank and drop
  the dead `scan_ai_title` fallback. Docs already note the fallback is moot.
- **`docs/durable-handoff-brief.md` scope call.** Its "Inner-loop inheritance mechanics, VERIFIED
  2026-06-17" note says the global `settings.json` references `danger-guard.sh` (false since
  `8602081`), and its setup.sh summary (it now links every hook, `agents/` and the CLIs) is stale
  too. Left unedited as a dated design snapshot. Decide: correct both, or keep it as history. The
  loop-engineering reference beside them is another repo's file and is NOT stale.
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
  `deckkit build /tmp/x && deckkit lint /tmp/x && deckkit package /tmp/x` (expect lint 0/0).
  `deckkit` is on PATH via `~/.local/bin`; otherwise use
  `~/.claude/skills/deck-production/scripts/deckkit`.
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
