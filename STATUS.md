# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design lives in the repo's `PLAN.md` or its doc,
> not only under `~/.claude/plans/`, which the next plan overwrites ([[plan-file-not-durable]]).

Last updated: 2026-10-29
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).
Lead branch: `chore/after-pr4` (the lead's STATUS commits; the lane next in merge order carries
them, `skills/lanes/SKILL.md` Lifecycle step 6).

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
  here. The config caps live lanes at 4 (Hayden kept 4 on 2026-10-25, for RAM), with locks
  `install` and `suite`.
  - **Merged through lanes or lead PRs, installed from main and closed:** #90 to #150
    (2026-10-12 to 2026-10-29). `gh pr list --state merged --limit 60` names each; the closed
    records under `.git/lanes/_closed/<id>-<date>/` hold the detail, and older STATUS text is in
    `git log -p -- STATUS.md`. Kept from them, since code alone doesn't say why:
    - #115 left the tab glyph's prompt at v4: an ask a reply only announces for later stays a
      documented known miss (`hooks/wants_input.py`'s docstring).
    - #145 (model-pin): `ANTHROPIC_MODEL` pins new sessions to Opus, so `/model` switches only
      the current session; effort stays unpinned (`CLAUDE_CODE_EFFORT_LEVEL` would lock
      `/effort` everywhere).
    - #148 (SP1 to SP13): sp-gaps' private replay (`~/scratch/sandbox-audit/sp-replay/replay.py`)
      is the regression check for the next policy-table change. Each review round found new
      bypasses in the option tables, so a later finding gets its own lane, not a reopened PR.
    - #144 (exam-prep): rules public, evidence private (Hayden, 2026-10-20).
    - Design notes: [[dotclaude-tab-bar]], [[dotclaude-remote-paste]], `PLAN.md` ("Next: a
      device-wide mute").
  - **Live lanes** (briefs in each record). Merge order: 1 lane-fixes (`fix/lane-small-bugs`,
    carries the lead's notes; opened 2026-10-29 on Hayden's "open": the unclosed `<!--`, trial
    no-ids and trial quiet lock items below), 2 pass-fixes (`fix/pass-compact`, opened
    2026-10-29 on Hayden's pick: the two compact-pass bugs and the excluded-guard rule 1 items
    below), 3 park (`feat/lane-park`, opened 2026-10-29 on Hayden's "a third lane since
    lane-fixes almost done": `lane park` below; overlaps lane-fixes, so it merges origin/main
    once lane-fixes lands), 4 practices (`feat/practices-auth-secrets`, its next PR; paused by
    Hayden since 2026-10-24, last so it blocks no install). The cap is full.
    Merged 2026-10-29 and installed from main: chrome-dup (#151: one chrome-devtools server,
    the plugin's; sandbox gap fixes N1 and N3's bun part, `hooks/sandbox-caches.sh`). Its
    install changed running sessions' sandbox live ([[cc-sandbox-config-reloads-live]]).
  - Once pushed, a lane merges `origin/main` into its branch, since force pushes are denied.

  Backlog:
  - **Next lane when a slot frees:** ports (below), after lane-fixes merges (same files).
  - G8 open probes (a) and (b) (Hayden's pick, 2026-10-14): Hayden runs
    `~/scratch/sandbox-audit/g8-probe/run.py` by hand with the sandbox off, because the auto-mode
    classifier refused the run. Results go into the private findings file's G8 section.
  - tmux 3.8 (Hayden's call 2026-10-14, "backlog it, close the lane"): test-build 3.8 in temp,
    rerun the menu-clip repro and the tmux suites. If it fixes the clip, install at a quiet
    moment (a server restart; claude-restore reopens the tabs) and drop the row-0 menu rule.
    Until then, 3.7c's default menus that dotclaude doesn't own still clip under a top bar.
  - **A development-practices skill suite (security, ux, then others)** (Hayden, 2026-10-19;
    context handed over by capella-studio's lead, session 5788b9fb). In lane practices; the
    first PR merged as #142 (the `server-code` skill, its `practices-check` gate hook and a
    planted-bug eval), auth-secrets next. Repo rules sit in a per-repo layer the skill reads if
    present (`.claude/practices/<skill>.md`); checks stay in each repo's tests. Hayden's scope:
    security covers everything (OWASP ASVS as the backbone, the reels' concrete failures as
    planted-bug evals), ux is the whole user experience and links `frontend-ui-discipline` for
    the UI part. Open for Hayden: the list and names. Lead's flags: `security-review` collides
    with a built-in skill; no capella code or unfixed gaps go in ([[dotclaude-public-repo]]); a
    skill says what enforces it (a hook at the event). Pairs with the AWS gap check below.
  - **Fixes from the AWS agentic-security gap check** (backlog, Hayden 2026-10-20: "not
    today"). Ten gaps (A1 to A10) with a proposed fix each, in the private findings file's "Gap
    check 2026-10-20" section. The lead suggests one lane for A1, A8 and A9 (rules, a test and
    docs; no design fork); the rest need Hayden's pick first.
  - **Stale worktree admin dirs** (lane mute's report, 2026-10-20). Closed lanes'
    `.git/worktrees/<id>/` come back holding only an empty `config.worktree`: sandbox mount
    points planted by long-running sessions whose sandbox path list predates the close. A
    prune is only temporary, and a sandboxed `prune` half-deletes live entries
    ([[sandbox-recreates-closed-worktree-dirs]], [[git-worktree-prune-shared]]). Leave them.
    Related: a read-only 0-byte `.git/config.lock` while a lane's sandboxed command runs (Notes).
  - **A compact pass puts live background writers into plan mode** (lane pass-fixes; a session
    in another repo reported it, 2026-10-20). Compact mode's resume prompt adds "Call
    EnterPlanMode first" to every unapproved pass (`resume_prompt` in
    `skills/pass/scripts/pass-respawn`); subagents follow the parent's permission mode, so a
    running writer was refused its write and handed back with 4 of 6 parts unstarted. Fix:
    with a live agent, the prompt says to plan in chat and enter plan mode after it hands back;
    also test a `permissionMode` in `agents/writer.md`.
  - **A compact pass's final Enter sometimes lands as a newline** (lane pass-fixes; Hayden's
    screenshot, 2026-10-22). The prompt and its Enter go out back to back while Claude Code is
    busy after the compact (inferred), so it reads a paste. Fix: wait until capture-pane shows
    the prompt in the box, send Enter, check the box emptied, one more Enter if not.
  - **excluded-guard rule 1 in a nested repo** (lane pass-fixes; session d3d62f82, 2026-10-26).
    (a) The `check_rule1` refusal reads as if the cwd were `.git`; it should say the cwd's repo
    isn't the project's, and that a session launched in that repo works. (b) The private
    follow-up (sandbox-audit FINDINGS, G5b) was probed on Hayden's ok (2026-10-29) and routed
    to lane pass-fixes with it.
  - **Two open sandbox gaps from lane chrome-dup's gap check** (high; lane chrome-dup,
    2026-10-25, reported to the lead 2026-10-29). Details are private: sandbox-audit FINDINGS,
    "Gap check 2026-10-25", rows N2 and N3 (the parts still OPEN). Each is a new lane; both
    reach `settings.json` and `hooks/sandbox-caches.sh` (#151, merged). N3's rest needs one probe per cache; N2's fix is a design fork
    for Hayden (options in the private row).
  - **Another `lane done` close-path gap** (lane done-safe's reviewer round 1, 2026-10-24).
    Details and the proposed fix are in the same private file, rows "cmd_done path trust" and
    "same, widened". The fix is a design change to `new`/`adopt`/`done` with a migration for
    existing lanes, so it needs Hayden's design call. Two low gaps ride with it (rows
    "seed_record from cmd_adopt" and "add_exclude"); their fix reuses #150's fd helpers.
    Lane-able (`skills/lanes/scripts/lane`, `lanelib.py`, `tests/lanes`).
  - **`lane trial` passes a suite that never ran** (lane lane-fixes; low; lane sp-gaps,
    2026-10-25). `trial_report` passes a failed suite that printed no test id on either run when
    both exits match, so a directory or a runner missing a flag cleared the gate. Lead's pick:
    with no ids on either run, fail and say "compare by hand".
  - **`lane trial` runs beside a repo's own "quiet machine" lock** (lane lane-fixes; low;
    capella-studio lead, session 80ab3852, 2026-10-26). A trial holds only `suite`, so capella's
    `lane lock quiet -- <gate>` ran beside one. Workaround sent: `lane lock quiet -- lane trial
    ...`, locks in that order. Lead's pick: a lanes-config key `trial_locks` naming extra locks
    every trial also takes, plus a docs line.
  - **An unclosed `<!--` in a Next block passes `handoff-check` and hides `Keep open:`**
    (lane lane-fixes; medium: `lane done` can close a lane with work left; capella-studio lane
    kindtheme, session a3c5cb2b, 2026-10-28). `section()` in `lanelib.py` strips only closed
    comments. Fix: an unclosed `<!--` fails `handoff-check` and makes `lane done` refuse, naming
    the line.
  - **`lane park <id>`: a parked state outside the cap** (lane park; feature; capella-studio lead, session
    6bceec36, on Hayden's pick there, 2026-10-29). Finished lanes wait hours for their merge turn
    holding a cap slot, a Claude session and dev servers (dotclaude's paused practices holds
    one now). Park refuses unless `handoff-check` passes, there is no `handoff?` flag, the tree is
    clean and the branch is pushed or has an open PR; it ends the lane's sessions with `done`'s
    proof rules and keeps the worktree, branch, record and claims. `ls` shows `parked` and still
    derives PR, `rebase`, `overlap` and `handoff?`; `open` unparks it (plan mode); `done` works as
    usual. The cap counts at `new` only, so park is a CLI-written flag under
    `<common-dir>/lanes/`, skipped by `new`'s count and checked by `open`. Lead's additions: park
    refuses while the lane holds a lock or the install hold; a parked lane gets no "main moved".
    Hayden's pick: a parked lane may unpark over a full cap to rebase and merge, at most one lane
    over at a time. Lane-able (`lane`, `lanelib.py`, `tests/lanes`, `docs/lanes.md`, the lanes
    skill), after lane-fixes merges.
  - **Ports: blocks per lane, `lane port`, `lane serve`** (feature; capella-studio lane prefs,
    session 78db7f95, 2026-10-29). A lane's run script started a dev server on a port another
    lane's dev held; the start failed and its checks silently tested the other server. Proposed:
    (1) a block of ports per lane, shown in `ls`; (2) `lane port claim [--purpose]`, `port who`,
    `port ls`; (3) `lane serve [--port N] -- <cmd>`: claim, start it in its own session, wait for
    its ready line or death, check the listener's pid is in that session; (4) a SessionStart
    "your ports" line. Hayden's scope (2026-10-29): PR 1 is (3) with (1); (2) and (4) a later PR.
    Only (3)'s listener check closes the silent wrong-server run. Lane-able (`lane`,
    `lanelib.py`, `tests/lanes`, `docs/lanes.md`, the lane-identity hook), after lane-fixes.
  - **Lanes skill: rebase only at your turn** (capella-studio lead, session 80ab3852, 2026-10-25;
    Hayden picked all three in capella's window). (A) The lead, step 7.6: only the lane next in
    merge order merges or rebases origin/main; the others get "main moved", check conflicts, and
    update at their turn. (B) After a conflict-free update, CI on the pushed head is the gate
    (dotclaude has no CI, so here that's the full local suites). (C) Optional train note: the
    second ready PR rebases onto the first's pushed head. Correction to (A): `git merge-tree`
    honours `.gitattributes` merge drivers and GitHub doesn't; ask the forge
    (`gh pr view N --json mergeable`) or use `git --attr-source=<empty tree> merge-tree
    --write-tree --name-only` (git 2.40+). `lane trial`'s `merge_tree` shares the blind spot.
    Lane-able (`skills/lanes/SKILL.md`, `docs/lanes.md`, `lane trial`), after lane-fixes.
  - **Practices suite input: dependency lifecycle** (capella-studio's lead, 2026-10-25; for
    lane practices at resume). SEC-60 covers only adding a dependency. Proposed: a
    per-dependency ledger kept in step by a test, an admission checklist, a production audit in
    PR checks with a triage file, and an update bot with a cooldown. capella's lane `deps` is the
    pilot. Scope is Hayden's call at resume.
  - **Practices suite input: cloudflare/security-audit-skill** (Hayden, 2026-10-27; for lane
    practices at resume). https://github.com/cloudflare/security-audit-skill (MIT): a six-phase
    audit skill (recon, coverage-led hunting, a fresh verifier per candidate, schema-checked
    findings). Compare with the suite's audit path: what to adopt, and whether to install it
    beside the suite or take its ideas only. Scope is Hayden's call at resume.
  - **excluded-guard refuses an over-matched command in an agent worktree** (lane mute's report,
    2026-10-20; not reproduced). Candidacy splits on `|`, `;` and `&&` without quotes, so a
    quoted excluded head in a `grep` pattern becomes a candidate, and in an agent worktree rule
    1 finds its `config.worktree` writable and refuses. Fix if it recurs: a quote-aware split.
  - **A custom CLAUDE_CONFIG_DIR breaks the hook layer** (lane config-dir, 2026-10-19): hook
    commands run `$HOME/.claude/hooks/...` and 16 hook files hard-code `~/.claude`, while
    `setup.sh` installs to `${CLAUDE_CONFIG_DIR:-$HOME/.claude}`. Matters for a new device
    ([[hayden-new-device-goal]]); unreachable on HAYPC.
  - Cosmetic: `lane ls`'s PR column reads `none` for a lane whose newest PR sits past the
    200-PR horizon (a per-branch `--state all` call fixes it); an untitled versioned claude's
    tab reads `2.1.303` (`tmux/claude.conf` and `tmux/tmux-tab-bar` fall back to
    `pane_current_command`).
  - Log only: a background session passing on its own (Hayden kept the bg pass manual,
    2026-10-18; don't build it without his ask); chrome-bg's gc judges `expires` by wall clock
    (a run can stop up to 0.6 s early; the holder's loop is monotonic since #126).
  - **Watch:** `~/.claude/CLAUDE.md` vanished once after a lane install (2026-10-20, before
    #140 made `setup.sh`'s links atomic); check `ls -la ~/.claude/CLAUDE.md` after each
    reinstall. Also asks the ask-check hook (#131) denies wrongly, and replies that skip the
    Waiting-on-you label (then a Stop-hook check is the follow-up).

  **The post-merge chain** (Hayden's design B, standing approval 2026-10-14): `skills/lanes/SKILL.md`,
  The lead, step 7. Lead commits on the lead branch ride the PR of the lane next in merge order,
  carried before each push and before ready (Lifecycle, step 6). A lane installs (`lane
  lock install -- ./setup.sh` from its worktree, sandbox off) only when next in merge order, and
  its install holds until the lead's reinstall from main.
- **Lanes, handoff-check and `/pass`** (Hayden's design, approved 2026-10-11; `PLAN.md`, behavior in
  `docs/lanes.md` and `skills/lanes/SKILL.md`). Four PRs:
  - All four PRs merged and installed: #86 (lanes core), #87 (the lead), #88 (`/pass`), #89
    (auto-pass, the banner and popup); smoke tests and as-built notes in PLAN.md,
    `git show cc6b3df:STATUS.md` (#86) and `git show e6040de:STATUS.md` (#87). The security follow-up's steps 0 and 1 shipped in #87 and
    #93/#100; its detail is private (`~/scratch/sandbox-audit/FINDINGS.md`, "Follow-up
    2026-10-11").
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
  - **Duplicate chrome-devtools servers (confirmed 2026-10-23):** every session runs both the
    user-scoped override (`chrome-devtools-mcp@1.9.0`, headless WSL flags) and the plugin's own
    (`@1.11.0`), about 150 MB per server with its npm wrapper, so about 1.7 GB across 11 sessions.
    `docs/chrome-devtools-wsl.md` still says user scope wins. Fix: keep one (drop the user-scoped
    entry or disable the plugin, whose skills use its namespace), then fix the doc. In lane
    chrome-dup since 2026-10-25: it first checks whether the plugin's 1.11.0 works on WSL, then
    asks Hayden which server to keep.
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
- **A stale trust entry from lane guard-b's smoke** (2026-10-14): `~/.claude.json` still trusts
  the deleted `/tmp/claude-1000/guard-b-tab`. A sandboxed session can recreate that path with its
  own `.claude/settings.json`, so the lead recommends removing the entry. Hayden removes it by
  hand (his call, 2026-10-14): the `projects` key `/tmp/claude-1000/guard-b-tab`. Its two
  transcripts expire on their own.
- **Two Write-tool bug drafts wait in `/feedback`** (Hayden's call to send): the overwrite-guard session's has the
  `claude -p` repro and the 2.1.285 boundary; the karaoke session's has the incident.

## Notes for next session
- **Next (lead, main checkout):**
  0. Four lanes run, cap full (In flight, Live lanes; state in their records, `lane ls`).
     When a slot frees: ports after lane-fixes merges, or N2/N3 (Hayden's pick). Running
     sessions took chrome-dup's allowWrite swap live at its install (2026-10-29): a session
     started before it needs a `/pass` before a sandboxed npm or bun install. Pending with Hayden, outside the lanes: `wsl --shutdown` at a break applies the 18 GB
     WSL cap set in `C:\Users\hayde\.wslconfig` on 2026-10-23 (backup `.wslconfig.bak-20261023`).
     Before each lead STATUS commit, grep it against the exam-prep denylist
     ([[lead-status-denylist-check]]). After each reinstall,
     check `ls -la ~/.claude/CLAUDE.md` (the Watch item). Watch that push asks open with the
     briefing (#137); if they skip it, the Stop-hook check is the follow-up (Hayden's pick).
  1. Hayden picks any further work from the backlog. On a bug report from another repo's session (CLAUDE.md, #125): check it
     against the code and log it in the backlog. When lanes run again, follow The lead in
     `skills/lanes/SKILL.md` (step 7 is the post-merge chain; never amend or rebase the lead
     branch). `lane new` refuses a branch name any PR used, and refuses when gh can't answer
     (lane branch-reuse); `--reuse-branch` overrides.
  - The lead's commits: `git log --first-parent main..chore/after-pr4` (STATUS only, plus merges
    of main). Session ab816898 (2026-10-20 to 25) ran `26b58ac..HEAD`: the #141, #143, #144,
    #145, #146 and #147 chains, lanes opened and closed, SP3 to SP7. Session 45664d28 (2026-10-20) ran `2c28e7e..26b58ac` on the lead branch: the #135
    chain (pr-horizon closed), the #133 chain (config-dir closed), lead PRs #136 and #137
    (merged, installed), lanes practices, summary-retire and link-atomic,
    and the CLAUDE.md watch item.
  - Open with Hayden, nothing for the lead to do: the capella-studio lead asked how a new lane
    should clear the excluded-command guard, and the lead recommended (2026-10-17) pointing
    capella's `core.hooksPath` at the main checkout's protected `.githooks` (absolute path)
    instead of one Edit deny rule per lane. If capella adopts it, the per-lane lines (polish,
    mcp, blockfix, keys) can leave `settings.machine.json` (Hayden's edit, then `./setup.sh`).
  - A config rewrite with the sandbox off (`git config`, `branch -d`, so `lane done` too) while a
    lane's suite runs can fail its SandboxReality test once: the rewrite swaps `.git/config`
    under the running sandbox's mount. Wait for `lane ls` to drop the `suite` lock. The other
    way round: while any lane's sandboxed command runs, an empty read-only `.git/config.lock`
    sits in the main checkout and every config write fails ("could not lock config file"). A
    lead PR's branch then takes `git branch --no-track <b> origin/main` plus `git worktree add
    <dir> <b>`, neither of which writes config (2026-10-19, #132).
  - A detached job started from a lane's held install keeps running in the lane after the
    lead's reinstall, and `lane done` refuses it by name ("nothing proves these processes ...
    are lane X's"). Seen 2026-10-18: Vulcan lane blockfix's session (fa4e8df1) began the
    post-upgrade quick canary (`delegation-ledger due --background quick audit`, 2.1.303) from
    cross-lane's `delegation-ledger` about when #123's reinstall ran. Wait for it to exit
    (about 5 min), then rerun `lane done`; the job is blockfix's, so never kill it.
  - **Watch (PR 4, live on HAYPC):** `context-watch.err` in the state dir (a Stop that timed out
    waiting for its reply, and the watcher's Python errors). Not yet seen live: a refused pass's
    toast, and Hayden's verdict on the rendered popup.
  - Verify from the main checkout (`test_subagent_policy` refuses to load under
    `.claude/worktrees/`): `tests/setup`, `tests/pass`, `tests/lanes`, `tests/delegation`. The
    last full run (lane guard-b at 210c7e2, 2026-10-14, under `lane lock suite`) was green:
    setup 992, lanes 260, delegation 671.
  - **Root cause of the timing flakes (lane lane-addr, 2026-10-14):** HAYPC's wall clock steps
    -2.7 s then +5.4 s about every 33 s (`time.time()` minus `time.monotonic()`; evidence:
    `.git/lanes/_closed/lane-addr-2026-10-14/.lane/artifacts/clock-steps.txt`). It matches the setup, ctx, handoff-reminder and
    ledger flakes. `systemd-timesyncd` is active inside WSL2 beside WSL's own host time sync,
    which likely meant two sources fighting. Hayden disabled it on 2026-10-17 (`inactive`,
    `disabled`). The swings stopped, but the clock still steps forward 0.3 to 0.6 s every 30 s
    with no time daemon running (a 120 s sample: +0.47, +0.59, +0.44, +0.29 at 1, 31, 61, 91 s).
    The likely source is Hyper-V's host time sync correcting a guest clock about 1.5% slow
    (inferred; clocksource `tsc`, `ptp0` present). Since #120, tests measure durations
    with `time.monotonic()`, and `tests/setup/test_clock_use.py` fails any `time.time()` in
    tests/ without a `# wall clock` marker. Shipped code has no guard; chrome-bg's TTL loop is
    its one duration site left (Backlog). Whether the flakes are gone takes repeated runs.
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
