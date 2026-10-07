# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design lives in the repo's `PLAN.md` or its doc,
> not only under `~/.claude/plans/`, which the next plan overwrites ([[plan-file-not-durable]]).

Last updated: 2026-10-07
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git, the linked plans and memory hold the detail)
- **tmux indicator and sounds** (live on HAYPC; [[dotclaude-tmux-indicator]]):
  `hooks/session-pane.sh` decides tab vs off-tab (its header holds the rules), `tmux-claude-status`
  maps a background session to its tab. Ring decisions: `ring.log`.
- **Sandbox gap fixes** (installed on HAYPC): code that runs outside the sandbox is `denyWrite`, tool
  tokens and shell history are `denyRead`. Findings: `~/scratch/sandbox-audit/FINDINGS.md` (private).
- **Merged and live:** PRs #62 to #73 (watch guard, hook payload sweep, git permission
  rules, `rm` never asks, tmux and sandbox fixes, the chrome-devtools 1.9.0 pin, the deck geometry
  gate, the Stop ring's quiet-while-busy (#72) and 1 s settle for a queued restart (#73), push and
  merge permissions (#71: `git push origin <branch>` and `gh pr create` run, anything that can
  reach `main` asks)), delegation hardening Stage 3 (PRs #42 to #55). README and
  `docs/delegation.md` hold the detail; lessons in [[cc-stop-hook-facts]].
- Older: `git log` and the PRs back to #10. One stays here because git can't show it: client deck
  data left the tree in PR #28, and its history was deliberately left as-is (Hayden's call).
- **Codex setup shared with a friend** (2026-09-29): private, ready to share at
  https://claude.ai/artifact/KWwrPkLsbMUi7Ugjfskqsz (republish by that URL).
- **tmux tabs come back after their server dies** (PR #70, installed 2026-10-05; design in
  `PLAN.md`, behavior in README "Tabs come back after a reboot", decisions in
  [[dotclaude-tmux-restore]]). **Untested for real:** Hayden's `wsl --shutdown`, then connect;
  `claude-restore --list` before, `$XDG_STATE_HOME/dotclaude/restore.log` after.
- **Green only for a real ask** (PR #74, live on HAYPC): the wait hook matches
  `permission_prompt|elicitation_dialog`. The cause is inferred, not proven; if a window goes green
  again with no ask, log `notification_type` in `tmux-state.sh`.
- **Overwrite guard and memory under git** (PR #75; installed and smoke-tested on HAYPC
  2026-10-06: a fresh session's blind Write was denied, and `memory.git` took its first commit).
  The brief's "Results" holds the experiments and Hayden's calls. **Watch:** `overwrite-guard.log`
  for denies that were really reads (the replay predicts about 6% of overwrites). The Write tool's
  own check is gone since 2.1.286; if Anthropic restores it, read-proof becomes redundant but
  harmless.
- **Delete guard for sandbox-off commands** (PR #78; installed from its branch and smoke-tested on
  HAYPC 2026-10-06: a fresh session's sandbox-off `rm -rf "$TMPDIR"/...` was
  denied before it ran). Rules and accepted limits: `hooks/delete_guard.py`'s docstring.
  Its replay numbers are in that docstring. **Watch:** `delete-guard.log` for a
  deny of a safe command. Same PR: the finish-before-merge rule (CLAUDE.md Boundaries, handoff
  step 5).

- **Read-only `gh` skips the classifier** (PR #79; installed from its branch, and a fresh auto-mode
  session ran the once-denied `gh pr checks --watch` on 2026-10-07). The live `autoMode` block was
  rewritten by hand the same day ([[cc-auto-mode-config-facts]]).

- **Dead `git push * :*` ask rule removed** (PR #80; a fresh session started with no warning on
  2026-10-07). Why, the probes and the accepted leak: [[dotclaude-danger-guard-retired]]. The test
  now rejects any `:*`.

- **Read-only git and pipe filters skip the classifier** (`fix/git-read-allow`; installed from its
  branch, and a fresh auto-mode session ran the once-denied `git status -sb | head -1` by rule on
  2026-10-07, while `git log --output=` asked). Each part of a pipe needs its own rule, hence
  `head`, `tail`, `wc`, `grep`. Unproven: a `cd X && ...` prefix (the probe model dropped it).
  The classifier refuses edits that add allow rules ("Self-Modification"): Hayden applies those.

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
  `delegation-ledger exclude --id <id> --why probe`.

## Blocked / decisions needed
- **Rescan the `rm` gap around 2026-11-04** (Hayden's call; the delete guard covers only
  sandbox-off deletes, so the sandboxed gap stands):
  `python3 -I ~/scratch/sandbox-audit/rm_scan.py 2026-11-04`. Sending the drafted
  `$CLAUDE_JOB_DIR/tmp` bug report is Hayden's call; `CLAUDE.md` carries the workaround.
- **Two Write-tool bug drafts wait in `/feedback`** (Hayden's call to send): this session's has the
  `claude -p` repro and the 2.1.285 boundary; the karaoke session's has the incident.

## Notes for next session
- **Next: Hayden picks the next workflow improvement**; deck-production S2 is deferred. First real
  check of #70: the next reboot (see Done). Recent work: PRs #67 to #76, #78 (#77 folded in), #79, #80 and
  `fix/git-read-allow` (`gh pr list --head fix/git-read-allow` for its number).
- **Verify the overwrite guard before touching it:** `python3 -m unittest discover -s tests/setup
  -t tests/setup` (`test_overwrite_guard.py`, `test_memory_git.py`, `test_claude_file_history.py`),
  then replay real history the way the brief's Results describes (a would-be deny rate near 17 in
  292 overwrites; a big jump means the proof rules broke).
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
