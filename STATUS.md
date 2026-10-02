# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable
> decisions ([[dotclaude-handoff-skill]], [[dotclaude-research-sourcing-skill]],
> [[dotclaude-chrome-devtools-wsl]]). Per-effort design rationale lives in its plan under `~/.claude/plans/`.

Last updated: 2026-10-01
Base: `main`. For branch / PR / push state, run `gh pr list` and `git log main..HEAD` (derive it; not
stored here).

## Done (recent; git, the linked plans and memory hold the detail)
- **Delegation hardening Stage 3, complete and live on HAYPC** (2026-09-30 to 10-01; PRs #42 to
  #46, range `d46449b..ce16b8a`; A1 is PR #48, range `c0a3241..1d09748`; A3 is PR #49, range
  `1d09748..65e7297`; A2 is PRs #51 and #52, range `0aa08f8..270dcb8`; A6 is PR #55, range
  `e4b790a..f3014c0`, with the legacy probes excluded and the quick canary green). Named spawns
  need a `team-` prefix; teammates are policed by role; `delegation-ledger canary`/`due`
  re-verify enforcement on their own; `open` and `watch` read liveness from the transcript, and
  `watch --summary` feeds the tmux bar. A2 nudges, then stops, an agent past its role's budget
  (`policy.toml` `[deadline]`). `audit --monthly` shows the numbers for retuning both, and `due`
  asks for it once the ledger is a month old.
  `docs/delegation.md` "Stage 3" holds the findings, the decisions and the test counts.
- **Small fixes** (PR #56, range `f3014c0..58a9b9d`): `setup.sh` links the portable skills into
  Codex, the `.mcp.json` stub is ignored, the status line's dead ai-title fallback is gone, and two
  history docs are corrected. Installed on HAYPC with `setup.sh`; the live `settings.json` didn't
  change.
- Older: `git log` and the PRs back to #10 hold it, and memory holds the decisions behind them.
  One stays here because git can't show it: client deck data left the tree in PR #28, and its
  history was deliberately left as-is (Hayden's call).

## In flight
- **Next: the delegation write-up** (Hayden wants it). Stage 2 and 3 are done, so the findings
  are complete.
  - **First call: the format.** A blog post (quotes and numbers, no raw evidence shipped) or a
    public repo (the harness and probes runnable, so far more must be scrubbed). Settle it before
    outlining. A new public repo is a new project, so place it with the `hq` skill.
  - **Sources, in order of use:**
    - `docs/delegation.md` in this repo: the findings, decisions, verified facts and test results
      for Stage 2 and 3, already written for readers. The history is in PRs #35 to #56.
    - `~/scratch/delegation-eval/` (2026-09-29 eval): `DECISION.md` (the decision, revised after
      review), `out/final.md`, `findings/` (landscape, transcripts, capabilities), and `data/`
      (`extract.py`, `analyze.py`, 384 extracted and classified agent records), with `tests/`.
    - `~/scratch/delegation-writeup/evidence/`: harness logs (`harness1.txt` to `harness3.txt`,
      `harness-codex.txt`) and three probe dirs (`sbprobe/`, `envprobe/`, `a2-step0/`).
  - **Privacy.** Raw transcripts embed private context, so never publish them as-is. Check
    `data/*.jsonl` and the harness logs for session ids, project names and paths before quoting
    them. `~/scratch/delegation-writeup/` also holds backups of `.zshrc`, `.zshenv` and `.mcp.json`
    from 2026-09-30: shell and MCP config that can carry tokens, so they stay out of anything
    published, and nobody has read them for this.
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
    Codex's skills).
    - A baseline key still wins over the live file's value, so copy `~/.claude/settings.json`
      first and diff it after.
    - Without a `settings.machine.json` overlay, install by hand per the docs' install order:
      the policy hook fails closed.
- **Codex setup shared with a friend** (Hayden's ask, 2026-09-29). The share page is BUILT and private:
  https://claude.ai/artifact/KWwrPkLsbMUi7Ugjfskqsz (source was a session scratchpad; republish by that
  URL). It links only four clean skills (coding-practices, research-discipline, ui-alignment,
  vetting-sources) and tells the friend never to run `setup.sh`. It is ready to share
  (`/codex:review` ran end to end on 2026-10-01).
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
- None open.

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
