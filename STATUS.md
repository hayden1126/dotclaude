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
  - **Files:** `docs/prose-is-not-a-permission.md` and `docs/images/delegation-layers.*`. The code
    links pin to `7ed72e9`, which is on `main`, so any merge style works.
  - **PR #60** (base `8ba422c`) applies a staged reader review and two verification rounds. The
    findings are in `~/scratch/delegation-writeup/prose-is-not-a-permission.reader-review.md`.
    The last round's fixes were checked by tests and greps, not by a fresh reviewer.
  - **Before publishing on Medium:**
    - Hayden reads it, and decides whether to cut it back toward the 2,500-word target Hayden set
      (it's about 3,750);
    - rerun SHAPE.md §6's grep after any edit;
    - make the hero image (the HTML comment at the top);
    - decide on the Codex model names.

    The aborted-first-launch beat is deferred.
  - **Sources and privacy:**
    - `~/scratch/delegation-writeup/SHAPE.md` (private, never in git) cites every number and
      holds the diagram spec (§8); [[svg-to-png-headless-render]] covers rendering it;
    - never publish raw transcripts or the eval data;
    - the `.zshrc`, `.zshenv` and `.mcp.json` backups beside SHAPE.md stay unread.
- **Watch guard follow-ups** (the guard itself is under Done).
  - **Open question:** does a Stop hook's `systemMessage` reach Hayden? The one live ack, around
    01:11 on 2026-10-03, went unseen (Hayden was away). Next: a one-minute live demo with Hayden
    watching; if the ack shows, close the docs' gap "The guard's ack rests on Claude Code's docs".
  - **An unnamed flaky test** erred twice under load on 2026-10-03, and didn't reproduce in 9
    runs. If it recurs, run with `-v` and name it.
- **`hooks/handoff-reminder.sh` fix, on branch `fix/handoff-reminder-subagents`** (derive its PR
  with `gh pr list`). It no longer fires on subagent or cross-session reports, and reads the
  prompt with python3 when jq is missing. Tests: `tests/setup/test_handoff_reminder.py`.
- **Delegation hardening: what is live on HAYPC** (Stage 2, plus the Stage 3 steps under Done;
  `docs/delegation.md`;
  `skills/delegation/SKILL.md` is the operating guide). Open items:
  - **Retune later, not now.** When `due` asks for `audit --monthly` (the date and the first
    sample sizes are in `docs/delegation.md` "Monthly audit (A6)"), retune `[deadline]` and
    `liveness.toml` only for the groups it doesn't mark `too few to retune`. After a probe run by
    hand in a live session, `delegation-ledger exclude --id <id> --why probe`.
  - The daily audit's "reports failing the contract: 3" is three known pre-fix rows from
    2026-09-30, gone from its window on 2026-10-07.
  - **Other machines:** `git pull` in `~/dotclaude`, then `./setup.sh`, both outside the sandbox
    (A4 and A3 changed `settings.json`, A2 adds a PostToolUse hook to it, and `setup.sh` now links
    Codex's skills). The watch guard adds a Stop hook and a baseline `permissions` object, which
    replaces a live one, so personal allow rules go in `settings.machine.json`.
    - A baseline key still wins over the live file's value, so copy `~/.claude/settings.json`
      first and diff it after.
    - Without a `settings.machine.json` overlay, install by hand per the docs' install order:
      the policy hook fails closed.
- **Codex setup shared with a friend** (2026-09-29): built, private and ready to share at
  https://claude.ai/artifact/KWwrPkLsbMUi7Ugjfskqsz (republish by that URL). It links four clean
  skills and says never to run `setup.sh`.
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
- **Whether to scrub `HAYPC`, `hq` and `~/vault` from STATUS.md, `skills/delegation/SKILL.md` and
  `BRIEF.md`.** The scrub left them in, because sessions and agents act on those files.

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
