# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design lives in the repo's `PLAN.md` or its doc,
> not only under `~/.claude/plans/`, which the next plan overwrites ([[plan-file-not-durable]]).

Last updated: 2026-10-19
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
  here. The config caps live lanes at 3, with locks `install` and `suite`.
  - Merged through lanes, installed from main and closed: #90 to #129 (2026-10-12 to
    2026-10-19), with lead PR #117 among them (its check passed: session 3a153a27's auto-pass
    loaded the handoff skill before pass-respawn's `handoff-check`). Last: bug-route, #125
    (`lane addr --repo <path> lead`, and a CLAUDE.md line sending a dotclaude bug met in another
    repo to this lead; the lead logs each report in the backlog. A durable inbox was rejected:
    revisit only if a report gets lost). Before it: launch-path, #124 (a claude run under its
    versioned path), and cross-lane, #123 (`lane ls` flags `overlap`, and `lane trial` runs
    before ready; `skills/lanes/SKILL.md`, Lifecycle).
    `gh pr list --state merged --limit 30` names each, and the closed records under `.git/lanes/_closed/<id>-<date>/` hold the detail (#116's
    post-merge smoke is in restore-effort's artifacts); tab-bar's design is in
    [[dotclaude-tab-bar]], remote-paste's live tests in [[dotclaude-remote-paste]]. #115 left the
    tab glyph's prompt at v4: an ask a reply only announces for later stays a documented known
    miss (`hooks/wants_input.py`'s docstring), since its one prompt round flipped 10 verdicts.
  - **Live lanes** (briefs in each record). Merge order (Hayden's reorder, 2026-10-20: the
    atomic link first, so no later install runs the old `link()`; link-atomic merged as #140
    the same day, summary-retire as #139): 1 exam-prep (`feat/exam-prep-skill`, carries the
    lead's notes; opened 2026-10-20 on Hayden's ok: the exam-prep skill suite below; ahead of
    practices and mute so it can install from its lane for the dry run before round 1's
    go/no-go, Thu 10/22), 2 practices (`feat/practices-suite`, opened 2026-10-19 at Hayden's ask: the skill
    suite below, researched from his project memories and online sources, then the security
    skill only; Hayden picked "security first"; its spec waits on his review). link-atomic and
    summary-retire opened 2026-10-20 on Hayden's ok (Backlog items below). summary-retire merged
    as #139, link-atomic as #140, pr-horizon as #135 and config-dir as #133 (2026-10-20):
    installed from main, the lanes closed. 3 mute (`feat/device-mute`, opened 2026-10-20 on
    Hayden's ok: the device-wide mute below, plus `setup-tmux.sh`'s `link()` fix, his pick the
    same day), 4 policy-fp (`fix/policy-false-denials`, opened 2026-10-20 on Hayden's ok: the
    three subagent-policy false denials below). Hayden raised the cap
    from 3 to 4 on 2026-10-20 for exam-prep; it is full.
  - **Lane ask quality: done** (2026-10-19 to 2026-10-20). ask-check merged as #131 and was
    installed from main 2026-10-20: a PreToolUse hook on AskUserQuestion (`hooks/ask_check.py`)
    denies risky asks with a checklist in the reason. branch-reuse merged as #130: `lane new`
    refuses a branch name any PR used (or when gh can't answer; `--reuse-branch` overrides),
    and handoff-check counts the checked-out branch. Lead PRs #132 and #134: CLAUDE.md's
    Waiting-on-you rule (an inline mark per item, then one plain-bullet list at the end); smoke
    passed 2026-10-20. Causes, rates and Hayden's picks: `~/scratch/lane-ask-quality/`
    (private: it quotes transcripts). **Watch:** asks the hook denies wrongly, and replies that
    skip the label (then the Stop-hook check is the follow-up).
  - The three lanes opened earlier on 2026-10-19
    merged, were installed from main and closed: chrome-ttl as #126 (chrome-bg's TTL on a
    monotonic deadline, plus coding-practices rule 8), tab-cmd as #127 (a claude run under its
    versioned path counts as claude in the tab scripts: Hayden's "trigger + confirm" design, the
    command looks like N.N.N and the pane tty's foreground group runs from `/claude/versions/`),
    json-depth as #128 (deep JSON reads as malformed wherever that is equal or stricter) and #129
    (malformed JSON fails closed at the trust sites, plus chrome-bg; Hayden's per-site picks are
    in its closed record's Decisions). `fix/json-depth-sweep` is deleted (Hayden's ok).
  - `lane new` with `|`, `<`, `>` or `;` inside its quoted `--goal` runs sandboxed and fails
    ("Read-only file system"), leaving a stray branch. The matcher likely reads them as compound
    syntax (inferred). Keep briefs free of them.
  - Once pushed, a lane merges `origin/main` into its branch, since force pushes are denied.

  Backlog:
  - G8 open probes (a) and (b) (Hayden's pick, 2026-10-14): Hayden runs
    `~/scratch/sandbox-audit/g8-probe/run.py` by hand with the sandbox off, because the auto-mode
    classifier refused the run. Results go into the private findings file's G8 section.
  - tmux 3.8 (Hayden's call 2026-10-14, "backlog it, close the lane"): test-build 3.8 in temp,
    rerun the menu-clip repro and the tmux suites. If it fixes the clip, install at a quiet
    moment (a server restart; claude-restore reopens the tabs) and drop the row-0 menu rule.
    Until then, 3.7c's default menus that dotclaude doesn't own still clip under a top bar.
  - **A development-practices skill suite (security, ux, then others)** (Hayden, 2026-10-19;
    context handed over by capella-studio's lead, session 5788b9fb; Hayden takes it up with the
    lead directly). Accepted so far: placement only. The suite lives in dotclaude; repo rules sit
    in a per-repo layer the skill reads if present (e.g. `.claude/practices/<skill>.md`, since a
    repo's `.claude/skills/` is write-denied in the sandbox); checks stay in each repo's tests.
    The capella lead suggests: triggers on concrete events (a migration, an `/api` route, an
    iframe, a loading state), checklist lines that name their proof, release skills call the
    checklists rather than copying them, a planted-bug eval per skill, and a security pilot first
    (mined read-only from capella). Hayden's scope (2026-10-19): security covers everything (SQL
    injection and the rest; Hayden sends the list), not only agents; ux is the whole user
    experience (lag and loading, which features serve users most, convenience), with UI a small
    part, so it links `frontend-ui-discipline` for that part. Open for Hayden: the list and
    names. In lane practices since 2026-10-19 (its record holds the state). Lead's flags: the
    name `security-review` collides with a built-in skill; dotclaude is public, so no capella
    code or unfixed gaps go in ([[dotclaude-public-repo]]); checklists in context get skipped, so
    a pilot should say what enforces it (a hook at the event, as ask-check does). Pairs with the
    AWS gap check below.
    Sources so far: six Instagram reels Hayden sent (2026-10-19; transcripts via getthescript.app),
    vibe-coding listicles. They fall into security (keys in the bundle, ids from the request, RLS,
    server-side sign-out, user enumeration, hashing, injection, rate limits), reliability (tests,
    retries with idempotency, circuit breakers, races, DR), legal (age checks, Google Fonts and
    GDPR, session replay, CAN-SPAM, renewal terms, DMCA agent, privacy policy) and launch (store
    metadata, Open Graph, Search Console, IndexNow). Lead's pick: OWASP ASVS as the security
    backbone, the reels' concrete failures as planted-bug evals.
  - **Fixes from the AWS agentic-security gap check** (backlog, Hayden 2026-10-20: "not
    today"). The check ran 2026-10-20 from the lead: ten gaps (ids A1 to A10, each re-checked
    against the code) with a proposed fix per gap, in the private findings file's "Gap check
    2026-10-20" section. The lead suggests one lane for A1, A8 and A9 (rules, a test and docs;
    no design fork) when a slot frees; the rest need Hayden's pick first. Details stay there
    ([[dotclaude-public-repo]]).
  - **Lanes tell the lead before an act past their worktree: merged as #136** (lead PR,
    2026-10-20, installed from main). New briefs drop the hand-written "Message the lead before
    any act..." Constraints line: the skill carries it (Lifecycle step 3).
  - **Retire the status-line summary rows: merged as #139** (lane summary-retire, 2026-10-20,
    installed from main and the lane closed; Hayden: "I don't read it anymore"). The Stop hook
    `hooks/session-summary.sh` asks Haiku for the tab label only; the rows and
    `statusline/session-summary.py` are gone, and `setup.sh` strips the two retired widgets from
    an existing ccstatusline layout (the live file is one row). It also took the ccstatusline
    crash fix: a wrongly shaped `lines` re-seeds with a backup, and a dir, FIFO or bad link at
    the destination warns and skips. The briefing-before-push rule merged as #137; a check
    follows only if asks skip it.
  - **The exam-prep skill suite** (Hayden's brief, `~/.claude/plans/exam-prep-skill-brief.md`,
    approved 2026-10-06, revised 2026-10-20; copied into lane exam-prep's artifacts): one
    umbrella skill, intake through tutor and retro, built from the Security I and AI 4701 runs.
    Round 1 (two midterms Tue 10/27) needs it loadable by Thu 10/22, else round 1 runs by hand.
    Hayden's pick (2026-10-20): rules public, evidence private (his quoted corrections, case
    notes, course and Ed ids stay in a private dir, [[dotclaude-public-repo]]). In lane exam-prep
    since 2026-10-20.
  - **A device-wide toggle for the toast and the sound** (Hayden, 2026-10-20): one switch that
    mutes the Windows toast and the notify ring for every session on the machine (no toggle
    exists today). Design settled 2026-10-20 (Hayden picked the lead's pick on all four forks:
    `PLAN.md`, "Next: a device-wide mute"). In lane mute since 2026-10-20 (its record holds the
    state).
  - **`setup-tmux.sh`'s own `link()` has #140's gap class** (lane link-atomic's report,
    2026-10-20). `setup-tmux.sh:62-71` moves a real file aside, then runs `ln -sfn`. GNU ln
    9.4 replaces a link with no missing window (the lead's race test: 0 misses in about 600k
    checks over 6000 swaps), but BSD/macOS `ln -sf` unlinks first, and the move-aside leaves a
    window on every platform on a first install. Fix: reuse #140's temp-name and `os.replace`
    swap (merged). In lane mute since 2026-10-20 (Hayden folded it in, since that lane edits
    `setup-tmux.sh:73-78` anyway).
  - **Stale worktree admin dirs break sandboxed commands now and then** (lane mute's report,
    2026-10-20; the lead checked). `.git/worktrees/` holds 45 entries `git worktree prune
    --dry-run` would remove ("gitdir file does not exist": closed lanes, old agent worktrees,
    test names like `tree1`), each holding only a 0-byte `config.worktree` the sandbox planted as
    a mount point (created about 5 s after each worktree). Claude Code's sandbox protects each
    entry's `commondir` and `config.worktree`, so every sandboxed command mounts over paths that
    don't exist; mute twice got bwrap's "Can't get type of source
    .git/worktrees/excluded-guard/commondir" (and once `.git/config.lock`), and the retry ran
    clean. Fix to try: `git worktree prune` (deletes under `.git/`: Hayden's ok first), then see
    whether running sessions plant the dirs again. Same family as config-dir's bwrap error in the
    Watch item below.
  - **Three false denials in the subagent policy** (lane exam-prep's dry run, 2026-10-20; the
    lead reproduced each with the code's own regexes). In `skills/delegation/scripts/subagent-policy`:
    (1) sed-exec: `SED_CMD`'s `/[A-Za-z0-9]*` branch (`:806`), meant for flags after the closing
    delimiter, also matches inside the pattern, so `sed -i 's/the same .../x/'` is refused as an
    `e` command (`:820`); (2) the same branch makes the w-flag finder read `s/show me/x/p` as a
    write to `me/x/p` (`:823`), which a read-only role is refused; (3) zsh-expansion
    (`:456`) searches the raw string for `=\(` before parsing, so a quoted heredoc line like
    `ux,uy=(x2-x1)/d` is refused. Delegated agents fall back to Edit or rewrite by hand. Fix:
    parse the s-command (skip pattern and replacement, then read flags) and judge `=(` only at
    a word start outside quotes, keeping `1e date`, `s/a/b/e`, `s/a/b/w f`, `cat =(ls)` and
    `${(f)x}` refused. In lane policy-fp since 2026-10-20.
  - **excluded-guard refuses an over-matched command in an agent worktree** (lane mute's report,
    2026-10-20; checked in code, not reproduced). Candidacy splits on `|`, `;` and `&&` without
    quotes, so a plain `grep` whose quoted pattern holds an excluded head becomes a candidate
    (`hooks/excluded_guard.py` docstring: "an over-match only adds checks"). In an agent
    worktree the gitdir isn't the project's, so rule 1 judges its `config.worktree`
    (`hooks/excluded_guard.py:522-525`), finds it writable and refuses. Only delegated writers
    hit it, and they report the denial. Fix if it recurs: a quote-aware split for candidacy.
  - **paste-inbox's sandbox skip: merged as #138** (lead PR, 2026-10-20, from lane
    summary-retire's report): sandboxed WSL interop now fails with `UtilBindVsockAnyPort`, not
    `UtilConnectUnix`, so 9 Laptop and LaptopPowerShell cases failed instead of skipping; one
    helper matches both. Tests only, so no reinstall (none held, and it skipped running the old
    `link()` again).
  - **Atomic install links: merged as #140** (lane link-atomic, 2026-10-20, installed from main
    and the lane closed). `setup.sh` builds each link under a per-pid temp name beside the target
    and swaps it in with one `os.replace`, so an installed path never goes missing.
    `~/.claude/CLAUDE.md` survived the lane's install (checked 77 s after) and the lead's
    reinstall from main. Keep the after-reinstall check below until a few clean installs pass.
  - **Watch: `~/.claude/CLAUDE.md` vanished after a lane install** (2026-10-20 00:53Z). Lane
    config-dir's `setup.sh` (00:52:28 to 00:52:38, sandbox off) linked it, then it was gone by
    00:53:02, with no backup (a symlink is removed, not backed up). Hayden relinked it by hand
    to `~/dotclaude-lanes/config-dir/CLAUDE.md` (the lead's own `ln -s` was refused as
    self-modification), and the #136 reinstall put it back on main, where it survived the
    sandboxed commands right after. config-dir's reinstall at 21:02 kept it too, across the same
    sandboxed `sandbox-denials` run; that session's sandbox config listed the resolved target,
    where after the loss it listed the literal path. So the loss points at `setup.sh`'s
    `link()` gap (`rm`, then `ln -s`) meeting some session's sandboxed command. Fix (merged as
    #140, above): make `link()` atomic, `ln -s` to a temp name beside the target, then `mv -T` over
    it, so the path never goes missing; lane-able (`setup.sh`, `tests/setup`). config-dir's timeline (its session 1f1393e7) rules out its code, its
    tests and install-state's prune; `~/.claude`'s mtime moved 190 ms after a sandboxed
    `delegation-ledger sandbox-denials` started. Its guess, unproven: the Bash sandbox. A
    sandbox config built while `link()` sat between `rm` and `ln -s` lists the literal path in
    denyWrite, and bwrap may plant and then clean up a mount point there. Check after each
    reinstall (`ls -la ~/.claude/CLAUDE.md`); a repro is a `setup.sh` run beside a loop of
    sandboxed commands. Related: the bwrap "Can't get type of source ... config.worktree" error
    config-dir hit while ask-check's worktree was being removed.
  - **A custom CLAUDE_CONFIG_DIR breaks the hook layer** (from lane config-dir, 2026-10-19;
    checked: 39 hook commands in `settings.json` run `$HOME/.claude/hooks/...`, while `setup.sh`
    installs to `${CLAUDE_CONFIG_DIR:-$HOME/.claude}`, and 16 files under `hooks/` hard-code
    `~/.claude`). Under a custom config dir every hook fails, and the `|| exit 2` ones block.
    Matters for a new device ([[hayden-new-device-goal]]); unreachable on HAYPC (unset).
    config-dir's PR covers only the delegation Python readers.
  - **`handoff?` past 200 PRs: fixed in #135** (lane pr-horizon, merged 2026-10-20, installed
    from main): `merges_of` asks gh per branch for a lane that switched, was adopted or predates
    the horizon. Tell capella-studio's lead (the reporter) once its lanes pick it up.
  - **`lane ls`'s PR column reads `none` for a lane whose newest PR sits past the 200-PR
    horizon** (cosmetic, from lane pr-horizon, 2026-10-19): a per-branch `--state all` call
    would fix it.
  - **An untitled versioned claude's tab reads `2.1.303`** (cosmetic, from lane tab-cmd,
    2026-10-19): `tmux/claude.conf:55-56` and `tmux/tmux-tab-bar:201` fall back to
    `pane_current_command` for a pane with no title.
  - **A background session passes on its own (log only: Hayden kept the bg pass manual,
    2026-10-18; don't build it without his ask)** (from lane pass-bg). After the turn ends, the
    waiter finds the pane running `claude attach <jobId>` (`tmux/claude-saved` already maps
    it), runs `claude stop <job>` and respawns that pane with a fresh claude. Unknowns: a pane
    in agent view leaves no link on disk, two clients can attach to one job, and the order of
    the stop and the respawn.
  - **chrome-bg's gc still judges `expires` by wall clock** (log only, from #126's PR body): a
    gc inside a clock step can stop a run up to 0.6 s early, and after a Windows sleep the holder
    outlives `expires` until the next gc. The holder's own loop is monotonic since #126.

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
- **A stale trust entry from lane guard-b's smoke** (2026-10-14): `~/.claude.json` still trusts
  the deleted `/tmp/claude-1000/guard-b-tab`. A sandboxed session can recreate that path with its
  own `.claude/settings.json`, so the lead recommends removing the entry. Hayden removes it by
  hand (his call, 2026-10-14): the `projects` key `/tmp/claude-1000/guard-b-tab`. Its two
  transcripts expire on their own.
- **Two Write-tool bug drafts wait in `/feedback`** (Hayden's call to send): the overwrite-guard session's has the
  `claude -p` repro and the 2.1.285 boundary; the karaoke session's has the incident.

## Notes for next session
- **Next (lead, main checkout):**
  0. Lanes exam-prep (merge order 1, carries the lead branch), practices (2), mute (3) and
     policy-fp (4) run; their state is in their records (`lane ls`). After each reinstall,
     check `ls -la ~/.claude/CLAUDE.md` (the Watch item). Watch that push asks open with the
     briefing (#137); if they skip it, the Stop-hook check is the follow-up (Hayden's pick).
  1. Hayden picks any further work from the backlog. On a bug report from another repo's session (CLAUDE.md, #125): check it
     against the code and log it in the backlog. When lanes run again, follow The lead in
     `skills/lanes/SKILL.md` (step 7 is the post-merge chain; never amend or rebase the lead
     branch). `lane new` refuses a branch name any PR used, and refuses when gh can't answer
     (lane branch-reuse); `--reuse-branch` overrides.
  - The lead's commits: `git log --first-parent main..chore/after-pr4` (STATUS only, plus merges
    of main). Session 45664d28 (2026-10-20) ran `2c28e7e..HEAD` on the lead branch: the #135
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
