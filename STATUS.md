# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design lives in the repo's `PLAN.md` or its doc,
> not only under `~/.claude/plans/`, which the next plan overwrites ([[plan-file-not-durable]]).

Last updated: 2026-10-05
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git, the linked plans and memory hold the detail)
- **tmux indicator and sounds** (live on HAYPC; [[dotclaude-tmux-indicator]]):
  `hooks/session-pane.sh` decides tab vs off-tab (its header holds the rules), `tmux-claude-status`
  maps a background session to its tab. Ring decisions: `ring.log`.
- **Sandbox gap fixes** (installed on HAYPC): code that runs outside the sandbox is `denyWrite`, tool
  tokens and shell history are `denyRead`. Findings: `~/scratch/sandbox-audit/FINDINGS.md` (private).
- **Merged and live:** PRs #62 to #66 (watch guard, hook payload sweep, git permission rules, `rm`
  never asks, tmux and sandbox fixes), delegation hardening Stage 3 (PRs #42 to #55). README and
  `docs/delegation.md` hold the detail.
- Older: `git log` and the PRs back to #10. One stays here because git can't show it: client deck
  data left the tree in PR #28, and its history was deliberately left as-is (Hayden's call).
- **Codex setup shared with a friend** (2026-09-29): private, ready to share at
  https://claude.ai/artifact/KWwrPkLsbMUi7Ugjfskqsz (republish by that URL).

## In flight
- **`deck-production`: the geometry gate is built** (`feat/deck-geometry`; design and the figures in
  `PLAN.md`, now history; behavior in SKILL.md "The geometry gate"). `deckkit geometry` drives
  headless Chrome over CDP (stdlib only) at every fragment step: contrast measured on pixels, AA by
  default, frozen at regulated rigor. Verified: 89 tests green, the reference deck's fixed map
  slide passes and its pre-fix version fails, whole-deck runs are identical (four regress runs on
  2026-10-05 gave the same geometry counts). The wiring (parity_check, doctor, SKILL.md, template,
  tests) had one review on 2026-10-05; its two real findings are fixed. Not taken: a reading near
  the contrast bar could flip golden counts (no flip seen; revisit only if regress ever flaps).
  - **Golden:** captured in the private repo on branch `chore/geometry-golden` (unmerged there);
    its `decks/_parity/README.md` lists the deck's real findings for that repo's session to fix
    (Hayden's call: record here, fix there). Until that branch merges, regress is green only with
    `--config`/`--goldens` pointed at that branch's `decks/_parity/` files; the private master's
    goldens have no geometry facts.
  - **Deferred, known:** gradient text (`background-clip:text`) is never judged; a color the canvas
    can't serialize reads as black; isolated glyph shots drop `filter`.
  - **Next block: S2 (fonts + PDF)**, then S4 (SKILL references + Workflow scripts), S5 (ingest +
    theme extractor), S6 (pptx export). S1-S4 is the usable product. The S2-S6 plan file is lost:
    write S2's plan into `PLAN.md`, replacing the geometry one.
  - Owners: SKILL.md (phases, gates), `deckkit` `COMMANDS` (CLI), `deckcfg.derive_rigor`, the
    private `decks/_parity/` goldens; no "S<n>" in shipped artifacts. Known gap:
    `deck.forward_targets` is declared, not detected; revisit when MUST/NEVER are enforced.
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
- **Branches ready, Hayden merges** (`gh pr list` for their state): `chore/cdt-1.9.0` (the pin,
  the CLAUDE.md kill rule; normal merge first), then `feat/deck-geometry` (stacked on it; **squash**,
  because 138c611 names two of the reference deck's selectors), and `fix/tmux-wait-subagent` any
  time (off `main`: a subagent's busy no longer covers a question's wait glyph, and a Stop with an
  agent or shell still running doesn't ring; neither is live until merged and pulled).
  - **After the merges:** outside the sandbox, `git fetch origin main:main` while still on
    `feat/deck-geometry`, then `git switch main`. Remove the old scratchpad worktree `tmuxfix`
    (`git worktree list`; it holds `fix/tmux-wait-subagent`), then delete the three local branches
    (`feat/deck-geometry` needs `-D` after a squash: confirm main's tree matches it first). Ask
    before removing the private repo's golden worktree (same old scratchpad; it holds
    `chore/geometry-golden`, which is pushed). No setup.sh.
- **Rescan the `rm` gap around 2026-11-04** (Hayden's call):
  `python3 -I ~/scratch/sandbox-audit/rm_scan.py 2026-11-04`. Sending the drafted
  `$CLAUDE_JOB_DIR/tmp` bug report is Hayden's call; `CLAUDE.md` carries the workaround.

## Notes for next session
- **Next: the post-merge cleanup** (Blocked), **then deck-production S2** (In flight). Recent
  ranges: `a52c798..fix/tmux-wait-subagent`, `a52c798..feat/deck-geometry` (its last three commits
  are the 2026-10-05 wiring fixes, after `f6eb927`).
- **Verify `deck-production` before touching it:** `deckkit regress` green (the config and goldens
  are in the private repo's `decks/_parity/`, README there has the command; see "Golden" above
  for which branch) and
  `python3 -m unittest discover -s tests/deck_production -t tests/deck_production` (needs the
  Puppeteer headless shell; full Chrome aborts inside the sandbox).
- **Verify delegation before touching it:** `tests/delegation` and `tests/setup` pass sandboxed;
  after changing a role, a hook or `codex-delegate`, run `delegation-ledger canary` outside the
  sandbox in the background (`docs/delegation.md` "The canary and the due checks").
- **A wrong tmux glyph or an unexpected ring:** read the last lines of
  `$XDG_STATE_HOME/dotclaude/ring.log`, and compare `~/.local/state/dotclaude/tabs` with `claude
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
