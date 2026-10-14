# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design lives in the repo's `PLAN.md` or its doc,
> not only under `~/.claude/plans/`, which the next plan overwrites ([[plan-file-not-durable]]).

Last updated: 2026-10-13
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
  reach `main` asks)), read-only `gh` allow rules (#79), the dead `git push * :*` rule dropped
  (#80), delegation hardening Stage 3 (PRs #42 to #55). README and `docs/delegation.md` hold the
  detail; lessons in [[cc-stop-hook-facts]], [[cc-auto-mode-config-facts]],
  [[dotclaude-danger-guard-retired]].
- Older: `git log` and the PRs back to #10. One stays here because git can't show it: client deck
  data left the tree in PR #28, and its history was deliberately left as-is (Hayden's call).
- **Codex setup shared with a friend** (2026-09-29): private, ready to share at
  https://claude.ai/artifact/KWwrPkLsbMUi7Ugjfskqsz (republish by that URL).
- **tmux tabs come back after their server dies** (PR #70, installed 2026-10-05; design in
  `PLAN.md`, behavior in README "Tabs come back after a reboot", decisions in
  [[dotclaude-tmux-restore]]). Ran for real on 2026-10-13 (`restore.log`, 13:58
  local).
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
- **Read-only git and pipe filters skip the classifier** (PR #81; installed from its
  branch, and a fresh auto-mode session ran the once-denied `git status -sb | head -1` by rule on
  2026-10-07, while `git log --output=` asked). The rules and their `cd`/`-C` limits: README.
  The classifier refuses edits that add allow rules ("Self-Modification"): Hayden applies those.
- **A plain `setup-tmux.sh` re-run keeps `base.conf`** (`fix/tmux-base-sticky`; installed from its
  branch 2026-10-07, and a plain re-run on HAYPC left `~/.tmux.conf` unchanged). The PR #70 install
  ran it without `--base`, which then meant "drop base.conf"; the live server kept `mouse on` until
  a reboot brought up a server with no mouse, click-to-tab or Ctrl-b Enter menu. `--no-base` now
  drops it.
- **The PR lifecycle short of a merge skips the classifier** (`fix/gh-pr-ready-allow`, Hayden's
  call 2026-10-09; installed from its branch, and a fresh auto-mode `claude -p` ran
  `gh pr ready 999999` straight to GitHub). The verbs and the test that ties rules to the
  workflow docs: README's permissions paragraph; why: [[policy-to-complete-rules]].
- **Star and Shelve Claude tabs** (PR #83, `feat/tmux-shelf`; installed from its branch and
  smoke-tested by Hayden on HAYPC 2026-10-08: right-click Star and Shelve, the Shelf, reopen).
  Right-click a tab, Ctrl-b S or Ctrl-b Enter: Star (★, a bookmark that follows the tab across
  `/clear`) or Shelve (save and close; restore skips it; reopening takes it off). Design,
  situations, limits: `PLAN.md`; behavior: README "Star and Shelve keep a chat after its tab
  closes"; decisions and traps: [[dotclaude-tmux-shelf]]. Pane to session comes from
  `~/.claude/sessions/<pid>.json` (undocumented; the registry is the fallback).

## In flight
- **dotclaude runs in lanes (since 2026-10-12).** The lead is the main checkout. Lanes live in
  `~/dotclaude-lanes/`, and each lane's state is in its record (`lane ls`, `lane asks`), not
  here. The config caps live lanes at 3, with locks `install` and `suite`.
  - Merged: `autopass-now` as #90, `attach-tabs` as #91 and `pass-busy` as #92 (2026-10-13), each
    installed by the lead from the main checkout. `/autopass` is now an immediate mod command,
    dotclaude's first. #92: an Artifact publish no longer blocks a plain pass (Claude Code
    2.1.296 arms an artifact watch per publish, shown to hooks as a `monitor` task whose id the
    model never sees; that is what refused capella-studio session e7cc7b9a's pass twice), and a
    `busy: tasks` refusal names each blocker (`pass-respawn --tasks`).
  - Merged and installed from main (2026-10-13): the lead's #94 (`fix/json-depth`: a state file
    too deep for json reads as malformed, in the pass-last readers, `autopass_state`,
    `session-registry`, `claude-saved` and `pass-respawn`) and lane `narrow-excluded` Part 1 as
    #93; the lane is closed (`lane done`, archived under `.git/lanes/_closed/`). A wider
    json-depth sweep (21 files, among them the delegation enforcement scripts and lane-close's
    files) is parked on `fix/json-depth-sweep`. Shipping any of it first needs a check of how
    each enforcement site fails (a caught error must not turn a deny into an allow). The trigger
    is near theoretical, so the sweep is optional.
  - Live: `lane-close` (opened 2026-10-13, Hayden's call: `lane done` ends the lane's own
    window and the leftovers that carry a lane session's id, the install lock holds until the
    lead's reinstall, setup.sh prunes links into lanes and says when sessions need a restart)
    `tab-bar` (opened 2026-10-13, below) and `lane-addr` (opened 2026-10-13 from its backlog
    entry below, whose text is now its Brief). **Merge order: 1 `lane-close`, 2 `tab-bar`, 3
    `lane-addr`.** The lead installs only the next to merge.
  - `lane new` with `|`, `<`, `>` or `;` inside its quoted `--goal` ran sandboxed and failed
    ("Read-only file system") even though `lane new *` is in `excludedCommands`. It left a
    stray branch, and nothing registered. The likely cause is that the matcher sees those
    characters as compound syntax (inferred). Keep lane briefs free of them, or run the
    command sandbox-off.
  - **/pass finding (2026-10-13):** lane-close's session 70e81418 had a compact pass time out
    (`pass.log` `outcome=timeout status busy`, pending lock `done:timeout`), then the tmux server
    died, and the session kept saying the pass was "still queued" for two more turns. The loud
    refusal notice never reached it (likely lost with the server). A timed-out pass should tell
    the session itself, not only the tmux client.
    Once pushed, a lane merges `origin/main` into its branch, since force pushes are denied.
  - Hayden split `narrow-excluded` (2026-10-13), after a safety classifier stopped three
    sessions while they read the sandbox code. Part 1, this lane's PR: the excluded-command
    inventory, the narrowed `excludedCommands`, the ask rules and their tests. Part 2, a
    follow-up lane the lead opens when a slot frees after `lane-addr`: a PreToolUse guard that lets an excluded command
    run only when its cwd's git dir and its PATH entries aren't sandbox-writable, then the allow
    lines for `lane ls/open/new/adopt/done` (an allow rule skips the classifier, so those land
    only behind the guard; Hayden applies them, since the classifier refuses edits that add
    allow rules). The lane's
    plan is rewritten in rule terms, and its sessions don't open the private findings. Codex is
    unavailable until the ChatGPT plan is renewed. If Part 1 stops again, Hayden applies it by
    hand.

  Backlog, after `narrow-excluded` merges (it may touch the same launch code): `lane init
  --model/--effort` repo defaults and `lane open --model/--effort` overrides, passed through to
  `claude`. Today `lane open` hardcodes the argv, so a lane's model or effort is set by hand in
  its window.

  **Lane `lane-addr` (opened 2026-10-13; Hayden's request via lane narrow-excluded, his pick
  "queue for the next slot"):**
  1. Stable lead/lane addressing. A session's name changes most turns, so a ListAgents name goes
     stale. The stable address is the messaging socket `uds:/run/user/1000/cc-socks/<pid>.sock`
     (`messagingSocketPath` in `~/.claude/sessions/<pid>.json`; tested live). Proposed:
     `lane addr <lane|lead>` prints it (live pid, cwd is the lane or the main checkout), and the
     lanes skill and the SessionStart line say to resolve it fresh before each send (a pass
     makes a new pid). The title's `[repo]` brackets look like ListAgents' `name [ref]`;
     narrow-excluded misaddressed the lead three times on that.
  2. Titles keep the main project: a lead stays `[dotclaude]` after a Bash `cd`
     (`hooks/session-title.sh`: the repo from `CLAUDE_PROJECT_DIR` or the session's launch cwd,
     not the payload cwd). Probe first: a Bash `cd` into a worktree moved the lead's primary
     working directory itself ([[bash-cd-moves-session-cwd]]). Hayden: "either the lead keeps
     its main project name, or the main project name is displayed on the left of the lead on
     that project's own lead/lanes row"; that row label is lane `tab-bar`'s (told 2026-10-13).
  Overlaps: lane-close (`skills/lanes/scripts/lane`), tab-bar (row label).

  **Lane `tab-bar` (opened 2026-10-13): stay on tmux, multi-row bar plus a phone layout.**
  Hayden picked tmux over a migration after the research page
  (https://claude.ai/artifact/E75uhqt2xskxUGQopLwvoA, private; tmux inventory in
  `~/scratch/tab-bar/INVENTORY.md`). The design is in the lane's Brief, and the decisions are
  in [[dotclaude-tab-bar]]: a row per lead with lanes, one shared row, overflow, at most 5 rows
  (pack, then `+N`); a narrow layout for the phone's grouped session; PR 2 adds manual drag
  between rows (spike first, popup board as the fallback), with placements kept in the tab
  record. Remote Control can't run `!` lines, so the phone needs the real pane. The
  remote-access side is private (the hq remote-access doc).
  - PR 1 merged as #96 (2026-10-13) before its fresh review and live smoke; the lead installed it
    from main the same day. Its review findings ride `fix/tab-bar-nav` (PR 1.5), with Shift+arrows
    that follow the bar's layout (Hayden's ask). Still open: Hayden's desktop and phone tap checks
    on the live bar, then PR 2.

  How lanes install, Hayden's call 2026-10-12: after its last review round, a lane runs
  `lane lock install -- ./setup.sh` from its own worktree, sandbox off. Until it merges, every
  session runs that lane's hooks. After the merge, the lead runs `git fetch origin main:main`,
  merges `main` into its branch `chore/after-pr4` (sandbox off), re-runs `./setup.sh` and
  `./setup-tmux.sh` from the main checkout under `lane lock install` (settings.json and
  `~/.tmux.conf` copied first and diffed), checks no installed link points into a lane, then
  proposes `lane done`. Lead STATUS commits ride the next lane PR to merge: that lane applies
  `git diff origin/main chore/after-pr4 -- STATUS.md` as one commit just before ready.
  - **Install gap found 2026-10-13:** `lane lock install` serializes only the setup.sh run, and
    the last run wins. Lane `attach-tabs` installed two minutes after lane `autopass-now` and
    replaced its links. Rule until tooling covers it: only the lane next in merge order
    installs, and the next lane waits for the lead's reinstall from `main`. The fix to build is a
    lock held from install until the merge.
  - **Messaging gap found 2026-10-13:** a lane's SendMessage to the lead failed "not reachable".
    A session's address is its full title, and `session-title.sh` rewrites the lead's title as
    the summary changes, so neither "dotclaude" nor a truncated title matched. Lead-to-lane sends
    work. Until it's fixed, the lead polls `lane asks`, and lanes put anything for the lead in
    their records.
- **Lanes, handoff-check and `/pass`** (Hayden's design, approved 2026-10-11; `PLAN.md`, behavior in
  `docs/lanes.md` and `skills/lanes/SKILL.md`). Four PRs:
  - PR 1 (lanes core) merged as #86 (`gh pr view 86`); its smoke test and guard replay are in
    `git show cc6b3df:STATUS.md`.
  - PR 2 (the lead) merged as #87 (`gh pr view 87`); its smoke test is in
    `git show e6040de:STATUS.md`.
  - **Security follow-up found while building PR 2** (excluded commands; detail and plan are
    private: `~/scratch/sandbox-audit/FINDINGS.md`, "Follow-up 2026-10-11"). **Step 0 is done on
    `feat/lanes-lead`, merged in #87**: the lanes config lives in the state dir, and what the
    sandbox can still write is checked before sandbox-off code acts on it (docs/lanes.md S3).
    Step 1 is lane `narrow-excluded`, and it merges before the work repo migration; step 2 later.
  - PR 3 (`/pass`) merged as #88 (`gh pr view 88`), installed with its allow rule; its live runs
    and the as-built notes are in PLAN.md PR 3 "As built".
  - PR 4 (auto-pass, the rendered banner and popup) merged as #89 (`gh pr view 89`), installed
    on HAYPC from its branch and smoke-tested (PLAN.md PR 4 "As built" and spikes A8 to A10).
  - The release skill in the work repos gets its post-release Next block and a closing
    `handoff-check` (PLAN.md PR 3 "Delta handoff"). Hayden's call (2026-10-12): it becomes the
    first lane of the work repo migration, after `narrow-excluded` merges, led from that repo's
    main checkout. A dotclaude lead can't open lanes there, because `lane` acts on the cwd repo.
  - Migrate the work repo (its own PR there). The concrete values and the
    incident ids are in `~/scratch/lanes/PRIVATE.md` (private).
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
- **Two Write-tool bug drafts wait in `/feedback`** (Hayden's call to send): the overwrite-guard session's has the
  `claude -p` repro and the 2.1.285 boundary; the karaoke session's has the incident.

## Notes for next session
- **Next (lead, main checkout): take lane-close's PR to ready and merge, then `tab-bar`, then
  `lane-addr`** ("In flight"). As of 2026-10-13, lane-close is done at `origin/main..3160bef`:
  - review rounds 3-6 and the live probe;
  - the lead's reviews of its post-merge fixes and of the G7 rounds (setup, sync and every
    `sys.executable` start run Python with `-I`; private findings G7), with the last round
    reviewed by the lead itself;
  - all four suites green in one run, installed from the lane, and smoked.

  Hayden approved its push and a draft PR; ready and merge still need his OK
  (`gh pr list --head feat/lane-close`). After the merge: reinstall from main, which releases
  lane-close's install hold (`lane ls` shows it). Then propose `lane done lane-close` and tell
  tab-bar it is next. Start with `lane ls` and `lane asks`. A lane is handed back only once
  `handoff-check -C <lane path>` passes and the board shows no `handoff?` flag. After each
  merge, follow the install step in "In flight", then `lane done <id>` once its session exits.
  narrow-excluded Part 2 opens at the next free slot.
  **Message a lane at its messaging socket**: `uds:/run/user/1000/cc-socks/<pid>.sock`, the
  `messagingSocketPath` in `~/.claude/sessions/<pid>.json` of the session whose cwd is in the
  lane. Resolve it fresh before each send, since a pass makes a new pid. A ListAgents name
  drifts, and a bare lane id is "not reachable". An idle lane still drains a message.
  - Local leftovers, never pushed: `fix/json-depth-sweep` (the parked sweep) and
    `fix/pass-last-recursion` (the same sweep under its first name, plus the writer's
    `worktree-agent-a8c1570566ac3d240` branch). Delete them once Hayden nods.
  - Tab restore (#70) ran for real: the tmux server died, and at 2026-10-13 13:58 local
    `restore.log` shows the open sessions restored to their tabs, with expected skips (a
    deleted directory, older sessions of one pane, a window closed before the server ended).
  - **Watch (PR 4, live on HAYPC):** `context-watch.err` in the state dir (a Stop that timed out
    waiting for its reply, and the watcher's Python errors). Not yet seen live: a refused pass's
    toast, and Hayden's verdict on the rendered popup.
  - Attach tabs: merged as #91 (behavior and limits: README "Star and Shelve", design and
    probes: `gh pr view 91`).
  - Verify from the main checkout (`test_subagent_policy` refuses to load under
    `.claude/worktrees/`): `tests/setup`, `tests/pass`, `tests/lanes`, `tests/delegation`. The
    last full run on `feat/autopass` (2026-10-12) was green: 532, 148, 155 and 646 tests.
  - **Flakes got worse under load (2026-10-13, lane-close's runs):** about half of loaded runs
    fail one timing test in `tests/pass` (a 600 s compact wait, a run killed at 900 s) or
    `tests/delegation` (`test_wait`'s 30 s subprocess timeout, `test_ledger` minute rounding);
    each passes 3/3 alone. Worth a small PR that bounds those waits on a fake clock; it is slowing
    every lane's verification.
  - **Flakes:** `tests/pass` fails timing asserts under a load spike, so judge it on a run of
    about 46 s. `test_tmux_hooks` flaked on `main` too; its ring-decision wait is now 15 s.
    Watch `seen()`'s 3 s wait, which also serves negative checks.
- **Astra waits on Hayden's plan** (`feat/codex-astra` merged as #85): two 2026-10-10 probes passed the audit (astra admitted,
  nothing disallowed), but even after a fresh `codex login` the turn gets a 400, "gpt-6-astra
  is not supported when using Codex with a ChatGPT account". Astra ran fine on 2026-09-29 and
  2026-10-08, so the plan lapsing is the likely cause (Hayden's read). Once the plan is back,
  rerun a one-line `--model astra` probe and `delegation-ledger exclude` it. The full canary
  is green on 2.1.296 (live 65/65, 2026-10-10); the hand-run watch-guard re-arm and Codex kill
  probe (`due.toml`) are still due for it. The delegation post still
  names only Sol and Terra (decide before Medium). Kaggle hosts for the RSNA repo
  (`api.kaggle.com`, `www.kaggleusercontent.com`) are not added: its `.claude/` has only
  `settings.local.json`, Hayden's call. Flaky, not from these branches: `test_tmux_hooks`
  `test_each_ring_decision_is_logged` failed once, then passed, and so did
  `test_a_mapped_background_session_rings_on_stop` (once in about seven full runs, never alone); `test_ledger`
  `test_open_warns_first_and_calls_the_session_unknown` read 4 min for a 5-min call once
  (a backward clock step, inferred). Then Hayden picks the next workflow improvement; deck-production S2 is deferred. First real
  check of #70: the next reboot (see Done). Recent work: `gh pr list --state merged --limit 10`.
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
