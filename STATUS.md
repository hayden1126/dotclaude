# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design lives in the repo's `PLAN.md` or its doc,
> not only under `~/.claude/plans/`, which the next plan overwrites ([[plan-file-not-durable]]).

Last updated: 2026-10-03
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git, the linked plans and memory hold the detail)
- **The hook payload sweep, merged in PR #63** (2026-10-03). The hooks are symlinked, so it's
  live. Commit messages hold the why, README's hook entries the behavior and the replay step,
  `tests/setup/` the cases. Accepted: "I think we should wrap up" doesn't fire; "handoff then
  commit hooks run twice" does.
- **The watch guard (background waits), merged in PR #62 and installed on HAYPC** (2026-10-02 to
  10-03). The behavior is in `docs/delegation.md` "Long waits", its open checks in that doc's
  "Next", and the decisions in `PLAN.md` (now history).
- **Delegation hardening Stage 3, complete and live on HAYPC** (2026-09-30 to 10-01, PRs #42 to
  #55). `docs/delegation.md` "Stage 3" holds the findings, the decisions and the test counts.
- Older: `git log` and the PRs back to #10 hold it (#56 was small fixes), and memory holds the
  decisions behind them.
  One stays here because git can't show it: client deck data left the tree in PR #28, and its
  history was deliberately left as-is (Hayden's call).

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
- **danger-guard retired; permission rules replace it** (branch `chore/post-63-decisions`,
  2026-10-03). The baseline `permissions` deny destructive git and ask before `git push`, `rm -r`
  and `rm -f`; README's two paragraphs on them say what's covered and what's caught by mistake,
  and [[dotclaude-danger-guard-retired]] holds the probe evidence. **Next:** Hayden merges, then
  installs. `settings.json` is copied, not linked, so the rules aren't live until then: copy
  `~/.claude/settings.json`, run `./setup.sh` outside the sandbox, and diff the two
  ([[dotclaude-setup-install-model]]). Then:
  - Check that a delegated writer's `rm -rf build` and `git -C <dir> stash push` in its
    worktree now ask (README says they should; not checked live). If that breaks delegation,
    revisit the `rm` and `git -C` push ask rules.
  - On each other machine, after `git pull`: `setup.sh` never removes old links, so
    `~/.claude/hooks/danger-guard.sh` dangles. Remove it (ask first), and any
    `settings.machine.json` hook that names it, which would now fail on every Bash call. HAYPC is
    already clean.
- **New-device parity audit** (queued 2026-10-03; [[hayden-new-device-goal]]). List HAYPC's
  local-only pieces and sort each into repo, opt-in installer, overlay template or private:
  `settings.machine.json`, `~/.claude/hooks/tmux-state.sh`, `~/bin/tmux-claude-status`, the
  `@claude_state` lines in `~/.tmux.conf`, user-scope MCP servers, plugins against
  `plugins/enabled.json`, the shell rc files. Then build the installers, tmux first, with
  `setup-chrome-wsl.sh` as the precedent (opt-in, not called by `setup.sh`). Remote access
  (`~/bin/tmux-remote`, the port-22 ForceCommand, `~/hq/docs/local/remote-access.md`) stays
  private. A drift check would fit the `setup.sh` doctor idea in [[deepseek-harness-eval]]. Both
  tmux scripts got `python3 -I` on 2026-10-03.
- **Hook follow-ups, after PR #63** (proposed 2026-10-03, not started):
  - **Move handoff-reminder's classifier into an importable module** (`hooks/handoff_reminder.py`
    behind the `.sh` shim), with one shared INJECTED list for the three prompt hooks. Tests and the
    replay would then run in seconds (the setup suite spends most of its 25 s spawning bash).
    `setup.sh` links only `hooks/*.sh`: link the module too, or have the shim find its own path.
  - The marker lists stay: the UserPromptSubmit payload has no origin field, and the prompt's
    transcript entry is written after the hook runs (probed 2026-10-03,
    [[cc-hook-payload-pitfalls]]).
- **Delegation hardening: what is live on HAYPC** (Stage 2 and 3, `docs/delegation.md`;
  `skills/delegation/SKILL.md` is the operating guide). Open items:
  - **Retune later, not now.** When `due` asks for `audit --monthly` (date and first sample sizes:
    `docs/delegation.md` "Monthly audit (A6)"), retune `[deadline]` and `liveness.toml` only for the
    groups it doesn't mark `too few to retune`. After a probe run by hand in a live session,
    `delegation-ledger exclude --id <id> --why probe`.
  - The daily audit's "reports failing the contract: 3" is three known pre-fix rows from
    2026-09-30, gone from its window on 2026-10-07.
  - **Other machines:** `git pull` in `~/dotclaude`, then `./setup.sh`, both outside the sandbox
    (it now also links Codex's skills). The baseline `settings.json` carries the delegation hooks,
    the watch guard's Stop hook and a `permissions` object that replaces a live one, so personal
    allow rules go in `settings.machine.json`. Copy `~/.claude/settings.json` first and diff it
    after (a baseline key still wins). Without an overlay, install by hand per the docs' install order: the policy hook
    fails closed.
- **Codex setup shared with a friend** (2026-09-29): built, private and ready to share at
  https://claude.ai/artifact/KWwrPkLsbMUi7Ugjfskqsz (republish by that URL). It links four clean
  skills and says never to run `setup.sh`.
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
  - Ownership: SKILL.md owns the phase model, gates and batch constants; `deckkit`'s `COMMANDS`
    owns the CLI surface (help is generated); `deckcfg.derive_rigor` owns the rigor rule; the
    goldens in the private client repo's `decks/_parity/` own the reference numbers. The plan
    owns block numbering only; no "S<n>" in shipped artifacts.
  - Known gap: `deck.forward_targets` is declared in `deck.toml`, not detected, so its default
    `false` means "nobody has said". Revisit when S3 enforces the storyboard MUST/NEVER grammar.

## Blocked / decisions needed
- None open.

## Notes for next session
- **Verify delegation before touching it:** `python3 -m unittest discover -s tests/delegation -t
  tests/delegation` and the same for `tests/setup` make no model calls and pass inside the sandbox
  (except from a checkout under `.claude/worktrees/`, where the policy tests need the sandbox off).
  `delegation-ledger canary` runs them, then the live harness (`tests/delegation/run.py --runner
  claude`, which spends model calls), and records the result: run it outside the sandbox, in the
  background, after changing a role, a hook or `codex-delegate`; after an upgrade, the
  session-start line says when. Counts live in `docs/delegation.md` "Tests". An unnamed delegation
  test erred twice under load on 2026-10-03 and didn't reproduce in 9 runs: if it recurs, run with
  `-v` and name it.
- **Verify `deck-production` before touching it:** `deckkit regress` as the README in the private
  client repo's `decks/_parity/` shows (`--config` and `--goldens` required) must print `parity:
  green`; it runs read-only and asserts the reference tree is unmodified. The reference deck is
  deliberately NOT migrated, so skipping this lets it drift silently. Smoke test: `deckkit new /tmp/x
  --title T --slides 6`, approve the storyboard frontmatter, then `deckkit build /tmp/x && deckkit
  lint /tmp/x && deckkit package /tmp/x` (expect lint 0/0); `deckkit` is on PATH via
  `~/.local/bin`, else `~/.claude/skills/deck-production/scripts/deckkit`.
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
