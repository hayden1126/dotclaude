# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design lives in the repo's `PLAN.md` or its doc,
> not only under `~/.claude/plans/`, which the next plan overwrites ([[plan-file-not-durable]]).

Last updated: 2026-10-04
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git, the linked plans and memory hold the detail)
- **tmux indicator and sounds, background sessions mapped to their tab** (2026-10-04, live on
  HAYPC). `hooks/session-pane.sh` decides tab vs off-tab (its header holds the rules): a
  `claude -p` run or an unmapped background session gets the toast only; `tmux-claude-status`
  maps a background session to the one client pane in its cwd (`$XDG_STATE_HOME/dotclaude/tabs`,
  limits in its header). Verified live: a `-p` run no longer clobbers its tab, dna_to_text rang
  with `pane=%2`. Handoff classifier: `hooks/handoff_reminder.py`. Ring decisions: `ring.log`.
- **Sandbox gap fixes** (2026-10-04, installed
  on HAYPC): code that runs outside the sandbox is `denyWrite`, tool tokens and shell history are
  `denyRead`. Findings and Hayden's calls: `~/scratch/sandbox-audit/FINDINGS.md` (private).
- **Merged and live:** `rm` never asks (PR #65; [[dotclaude-danger-guard-retired]]), permission
  rules for destructive git (PR #64), the hook payload sweep (PR #63), the watch guard (PR #62),
  delegation hardening Stage 3 (PRs #42 to #55). README and `docs/delegation.md` hold the detail.
- Older: `git log` and the PRs back to #10, and memory for the decisions. One stays here because
  git can't show it: client deck data left the tree in PR #28, and its history was deliberately
  left as-is (Hayden's call).
- **Codex setup shared with a friend** (2026-09-29): private, ready to share at
  https://claude.ai/artifact/KWwrPkLsbMUi7Ugjfskqsz (republish by that URL).

## In flight
- **The delegation post: on `main`, revised in PR #60, not yet on Medium.**
  - **Files:** `docs/prose-is-not-a-permission.md` and `docs/images/delegation-layers.*`; the code
    links pin to `7ed72e9`, on `main`.
  - **PR #60** (base `8ba422c`) applied a staged reader review and two verification rounds
    (findings: `~/scratch/delegation-writeup/prose-is-not-a-permission.reader-review.md`); the last
    round's fixes were checked by tests and greps, not by a fresh reviewer.
  - **Before Medium:** Hayden reads it and decides whether to cut it toward the 2,500-word target
    (it's about 3,750); rerun SHAPE.md §6's grep after any edit; make the hero image (the HTML
    comment at the top); decide on the Codex model names. The aborted-first-launch beat is deferred.
  - **Sources and privacy:** `~/scratch/delegation-writeup/SHAPE.md` (private, never in git) cites
    every number and holds the diagram spec (§8; [[svg-to-png-headless-render]]). Never publish
    raw transcripts or the eval data; the `.zshrc`, `.zshenv` and `.mcp.json` backups beside
    SHAPE.md stay unread.
- **Other machines:** `git pull` in `~/dotclaude`, then `./setup.sh`, both outside the sandbox.
  Copy `~/.claude/settings.json` first and diff it after: the baseline's `permissions` object
  replaces the live one (personal allow rules go in `settings.machine.json`), and a baseline key
  still wins. Without an overlay, install by hand per the docs' install order: the policy hook
  fails closed. Then remove the dangling `~/.claude/hooks/danger-guard.sh` link (`setup.sh`
  never removes old links; ask first) and any `settings.machine.json` hook naming it. HAYPC is
  done.
- **New-device parity audit: tmux, Codex, the overlay example and the chrome-devtools pin done.**
  The inventory and a recommendation per piece are private in `~/scratch/parity-audit/INVENTORY.md`
  ([[hayden-new-device-goal]]). The WSL override now pins `chrome-devtools-mcp@1.9.0` (branch
  `chore/cdt-1.9.0`, installed on HAYPC: `claude mcp get chrome-devtools` shows it Connected; a
  session picks it up on restart). `setup-chrome-wsl.sh`'s header has why it also clears the
  profile's restored tabs. Left: a `shell/` snippet, only if a second device is coming. A drift
  check would fit the `setup.sh` doctor idea in [[deepseek-harness-eval]].
  - **Unchecked:** sessions load the plugin's own `chrome-devtools` server (no WSL flags) beside
    the user-scoped override: both tool namespaces show up, and `npm exec chrome-devtools-mcp@1.9.0`
    runs flagless. The doc says user scope wins, which doesn't match. Check whether the plugin's
    copy works on WSL and whether to disable it.
- **Hook follow-up:** the INJECTED marker lists stay one per prompt hook, kept equal by
  `test_the_three_lists_agree` ([[cc-hook-payload-pitfalls]] has why).
- **Delegation hardening: what is live on HAYPC** (Stage 2 and 3, `docs/delegation.md`;
  `skills/delegation/SKILL.md` is the operating guide). Open items:
  - **Retune later, not now.** When `due` asks for `audit --monthly` (date and first sample sizes:
    `docs/delegation.md` "Monthly audit (A6)"), retune `[deadline]` and `liveness.toml` only for the
    groups it doesn't mark `too few to retune`. After a probe run by hand in a live session,
    `delegation-ledger exclude --id <id> --why probe`.
  - The daily audit's "reports failing the contract: 3" is three known pre-fix rows from
    2026-09-30, gone from its window on 2026-10-07.
- **`deck-production` blocks S2-S6** (plan: `~/.claude/plans/explore-our-entire-workflow-bright-shamir.md`,
  missing from HAYPC on 2026-10-01; find it on the machine that wrote it, or rebuild it from here).
  S1 shipped and verified (base `8602081`): the skill has the phase model and the core loop but no
  orchestration layer, so an agent can't yet run a deck end to end.
  - **Next: block S3, the geometry gate** (`geometry.py` + `geometry_probe.js` + a declarative
    `geometry.rules.toml`), because it catches the defect class screenshots miss. It must FAIL on a
    fixture reproducing the reference deck's s17 overlap (unbounded caption `max-width`, no panel
    background, anchors ~95px apart) and PASS on the real s17 as it stands.
  - Then S2 (fonts + PDF), S4 (SKILL references + 6 Workflow scripts), S5 (ingest + theme
    extractor), S6 (pptx export). S1-S4 is the usable product.
  - Owners: SKILL.md (phases, gates), `deckkit` `COMMANDS` (CLI), `deckcfg.derive_rigor`, the
    private `decks/_parity/` goldens; no "S<n>" in shipped artifacts. Known gap:
    `deck.forward_targets` is declared, not detected; revisit when S3 enforces MUST/NEVER.

## Blocked / decisions needed
- **Rescan the `rm` gap around 2026-11-04** (kept as a known gap, Hayden's call):
  `python3 -I ~/scratch/sandbox-audit/rm_scan.py 2026-11-04`. Sending the drafted
  `$CLAUDE_JOB_DIR/tmp` bug report is Hayden's call; `CLAUDE.md` carries the workaround.

## Notes for next session
- **Next: deck-production S3, the geometry gate** (In flight has the target; its design goes in
  `PLAN.md` on `feat/deck-geometry`, stacked on `chore/cdt-1.9.0`). Branch `chore/cdt-1.9.0` (the pin and a CLAUDE.md kill rule) waits on Hayden's PR
  call. Other machines pick up main with `./setup.sh`, plus `./setup-tmux.sh` where tmux is used
  (README has the overlay caveat).
- **A wrong or missing tmux glyph:** compare `~/.local/state/dotclaude/tabs` with `claude agents
  --json` and `tmux list-panes -a -F '#{pane_id} #{pane_current_command} #{pane_current_path}'`.
  Unprobed: whether `/clear` inside a background session changes the `sessionId` it lists.
- **A ring from an unexpected session:** read the last lines of
  `$XDG_STATE_HOME/dotclaude/ring.log` (session id, kind, attended, pane, dir) before guessing.
- The delegation post waits on Hayden's read.
- **Verify delegation before touching it:** both unit suites (`tests/delegation`, `tests/setup`)
  pass sandboxed; after changing a role, a hook or `codex-delegate`, run `delegation-ledger canary`
  outside the sandbox in the background (`docs/delegation.md` "The canary and the due checks"). An
  unnamed delegation test erred twice under load on 2026-10-03: if it recurs, run `-v` and name it.
- **Verify `deck-production` before touching it:** `deckkit regress` green (SKILL.md; the config
  and goldens are in the private client repo's `decks/_parity/`). Smoke: `deckkit new /tmp/x
  --title T --slides 6`, approve the storyboard, then `build`, `lint` (expect 0/0), `package`.
- research-sourcing (optional): the thorough-tier planted-fabrication spot-check was never run end
  to end, and only Agent-tool subagents were tested, not a real Workflow run.
- Deferred handoff work (the PreCompact/Stop safety net, the loop-engineering handoff) is in
  [[dotclaude-handoff-skill]].
- Evaluated and SKIPPED, do not re-raise: (a) wiring `handoff-reminder.sh` into the
  loop-engineering inner loop (its one machine prompt has no wrap-up phrase); (b) cross-platform
  notifiers for the toast (YAGNI on WSL-only); (c) a CLAUDE.md nudge to create more native tasks
  (the session-summary line already grounds "what/where"; revisit only if a 4-6 step job with no
  tasks shows up, scoped to multi-step work); (d) scrubbing `HAYPC`, `hq` and `~/vault` from
  STATUS.md, `skills/delegation/SKILL.md` and `BRIEF.md` (the post's code links pin `7ed72e9`,
  which already shows them, and agents act on the exact paths).
- A fresh WSL clone needs `./setup-chrome-wsl.sh` once ([[dotclaude-chrome-devtools-wsl]]).
