# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design lives in the repo's `PLAN.md` or its doc,
> not only under `~/.claude/plans/`, which the next plan overwrites ([[plan-file-not-durable]]).

Last updated: 2026-10-06
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git, the linked plans and memory hold the detail)
- **tmux indicator and sounds** (live on HAYPC; [[dotclaude-tmux-indicator]]):
  `hooks/session-pane.sh` decides tab vs off-tab (its header holds the rules), `tmux-claude-status`
  maps a background session to its tab. Ring decisions: `ring.log`.
- **Sandbox gap fixes** (installed on HAYPC): code that runs outside the sandbox is `denyWrite`, tool
  tokens and shell history are `denyRead`. Findings: `~/scratch/sandbox-audit/FINDINGS.md` (private).
- **Merged and live:** PRs #62 to #69 (watch guard, hook payload sweep, git permission rules, `rm`
  never asks, tmux and sandbox fixes, the chrome-devtools 1.9.0 pin, the deck geometry gate, the
  tmux wait and quiet-busy-stop fixes), delegation hardening Stage 3 (PRs #42 to #55). README and
  `docs/delegation.md` hold the detail.
- Older: `git log` and the PRs back to #10. One stays here because git can't show it: client deck
  data left the tree in PR #28, and its history was deliberately left as-is (Hayden's call).
- **Codex setup shared with a friend** (2026-09-29): private, ready to share at
  https://claude.ai/artifact/KWwrPkLsbMUi7Ugjfskqsz (republish by that URL).
- **tmux tabs come back after their server dies** (PR #70, installed 2026-10-05; design in
  `PLAN.md`, behavior in README "Tabs come back after a reboot", decisions in
  [[dotclaude-tmux-restore]]). Open tabs are recorded only once restarted or `/clear`ed after
  install. **Untested for real:** Hayden's `wsl --shutdown`, then connect; `claude-restore --list`
  before, `$XDG_STATE_HOME/dotclaude/restore.log` after. Accepted limits are in PR #70.
- **Stop ring quiet-while-busy, fixed for real** (PR #72, 2026-10-05): #69 matched internal task
  names, but `background_tasks[].type` is a friendly label (`shell`, `subagent`), so it never
  fired. Merged and live on HAYPC; verified live (`quiet busy=1 tasks=shell`). Lesson in [[cc-stop-hook-facts]].
- **Stop ring settles 1 s for a queued restart** (PR #73, merged and live 2026-10-06): a
  task finishing during the final reply is queued and missing from `background_tasks`, so the Stop
  rang; now it logs `quiet resumed=1` when a dequeue follows. Verified live (15:37:38).
- **Push and merge permissions** (PR #71, installed 2026-10-05): `git push origin <branch>` and
  `gh pr create` run; anything that can reach `main` and merges ask (README "permissions"
  paragraph). Claude still asks in chat first (CLAUDE.md).

## In flight
- **`deck-production`: deferred (Hayden, 2026-10-05: workflow improvements first).** The geometry
  gate is merged (#68): behavior in SKILL.md "The geometry gate", design in git history (`PLAN.md`
  before the tmux-restore design). Its golden is on the private repo's unmerged
  `chore/geometry-golden` (its `decks/_parity/README.md` lists the deck's findings, fixed there);
  until it merges, regress needs `--config`/`--goldens` from that branch. Deferred gaps: gradient
  text is never judged, an unserializable color reads as black, isolated glyph shots drop
  `filter`; a reading near the contrast bar could flip golden counts (revisit only if regress
  flaps). Next block when resumed: S2 (fonts + PDF; decide whether `fingerprint` joins it), then
  S4 (references + Workflow scripts), S5 (ingest + theme), S6 (pptx); S1-S4 is the usable
  product. The S2-S6 plan is lost: write S2's into `PLAN.md`. Owners: SKILL.md (phases, gates),
  `deckkit` `COMMANDS`, `deckcfg.derive_rigor`, the private goldens; no "S<n>" in shipped
  artifacts. `deck.forward_targets` is declared, not detected.
- **New-device parity audit: done except a `shell/` snippet** (only if a second device is coming).
  Inventory: `~/scratch/parity-audit/INVENTORY.md` (private; [[hayden-new-device-goal]]). The WSL
  override pins `chrome-devtools-mcp@1.9.0` (`setup-chrome-wsl.sh`'s header has why it also clears
  the profile's restored tabs). A drift check would fit the `setup.sh` doctor idea in
  [[deepseek-harness-eval]].
  - **Unchecked:** sessions load the plugin's own `chrome-devtools` server (no WSL flags) beside the
    user-scoped override: both tool namespaces show up, and a flagless `npm exec
    chrome-devtools-mcp@1.9.0` runs. `docs/chrome-devtools-wsl.md` and the memory say user scope
    wins. Check whether the plugin's copy works on WSL and whether to disable it; then fix the doc.
- **The delegation post: on `main`, revised in PR #60, not yet on Medium.** Files:
  `docs/prose-is-not-a-permission.md`, `docs/images/delegation-layers.*` (code links pin `7ed72e9`).
  Before Medium: Hayden reads it and decides whether to cut toward 2,500 words (it's about 3,750);
  rerun SHAPE.md §6's grep after any edit; make the hero image; decide on the Codex model names.
  Sources and privacy: `~/scratch/delegation-writeup/SHAPE.md` (private, never in git; diagram spec
  §8, [[svg-to-png-headless-render]]). Never publish raw transcripts or the eval data; the backups
  beside SHAPE.md stay unread.
- **Other machines:** `git pull` in `~/dotclaude`, then `./setup.sh`, both outside the sandbox. Copy
  `~/.claude/settings.json` first and diff it after: the baseline's `permissions` replaces the live
  one (personal rules go in `settings.machine.json`). Without an overlay, install by hand per the
  docs' install order: the policy hook fails closed. Remove a dangling
  `~/.claude/hooks/danger-guard.sh` link (ask first). HAYPC is done. `./setup-tmux.sh` where tmux is
  used; a fresh WSL clone needs `./setup-chrome-wsl.sh` once.
- **Delegation hardening: live on HAYPC** (`docs/delegation.md`; `skills/delegation/SKILL.md` is the
  operating guide). Retune `[deadline]` and `liveness.toml` only when `due` asks for `audit
  --monthly`, and only for groups not marked `too few to retune`. After a probe run by hand,
  `delegation-ledger exclude --id <id> --why probe`. The daily audit's "reports failing the
  contract: 3" are pre-fix rows from 2026-09-30, gone from its window on 2026-10-07.

## Blocked / decisions needed
- **Rescan the `rm` gap around 2026-11-04** (Hayden's call):
  `python3 -I ~/scratch/sandbox-audit/rm_scan.py 2026-11-04`. Sending the drafted
  `$CLAUDE_JOB_DIR/tmp` bug report is Hayden's call; `CLAUDE.md` carries the workaround.

## Notes for next session
- **Next: Hayden picks the next workflow improvement**; deck-production S2 is deferred. First
  real check of #70: the next reboot (see Done). Recent work: PRs #67 to #73.
- **Verify `deck-production` before touching it:** `deckkit regress` green (the config and goldens
  are in the private repo's `decks/_parity/`, README there has the command; the deck-production
  item says which branch) and
  `python3 -m unittest discover -s tests/deck_production -t tests/deck_production` (needs the
  Puppeteer headless shell; full Chrome aborts inside the sandbox).
- **Verify delegation before touching it:** `tests/delegation` and `tests/setup` pass sandboxed;
  after changing a role, a hook or `codex-delegate`, run `delegation-ledger canary` outside the
  sandbox in the background (`docs/delegation.md` "The canary and the due checks").
- **A wrong tmux glyph or an unexpected ring:** read the last lines of
  `$XDG_STATE_HOME/dotclaude/ring.log` (stop lines carry `tasks=<labels>` in flight; `quiet resumed=1` means a queued input restarted
  the turn within the settle second), and compare `~/.local/state/dotclaude/tabs` with `claude
  agents --json` and `tmux list-panes -a -F '#{pane_id} #{pane_current_command}
  #{pane_current_path}'`. Unprobed: whether `/clear` in a background session changes its sessionId.
- research-sourcing (optional): the thorough-tier planted-fabrication spot-check was never run end
  to end, and only Agent-tool subagents were tested, not a real Workflow run.
- Deferred handoff work (the PreCompact/Stop safety net, the loop-engineering handoff) is in
  [[dotclaude-handoff-skill]].
- Evaluated and SKIPPED, do not re-raise: (a) wiring `handoff-reminder.sh` into the
  loop-engineering inner loop; (b) cross-platform notifiers for the toast (YAGNI on WSL-only);
  (c) a CLAUDE.md nudge to create more native tasks (revisit only if a 4-6 step job with no tasks
  shows up); (d) scrubbing `HAYPC`, `hq` and `~/vault` from STATUS.md, `skills/delegation/SKILL.md`
  and `BRIEF.md` (the post's code links pin `7ed72e9`, which already shows them).
