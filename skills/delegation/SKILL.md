---
name: delegation
description: How to hand work to another agent (a subagent, an agent-team teammate, or Codex) so it stays in scope and reports back. Use before any Agent spawn or Codex run that does real work. Covers which role to pick, the brief, checking the report, and recovering unfinished delegations after a crash.
---

# Delegation

Prose covers judgment; enforcement covers authority, acceptance and liveness. The role you
pick fixes what an agent can do, because its tools and its working directory set its
reach. The brief tells it what to do and why. Never rely on the brief to limit authority:
an agent told "don't edit" in prose still can if its role has the tools. That is the root
cause of every drift case in the 2026-09-29 evaluation (`docs/delegation.md` in dotclaude).

## 1. Pick the role

| The task needs | Spawn | What it can do |
|---|---|---|
| Find or read code, docs, web pages | `Explore` (ours, overrides the built-in) | Read, Grep, Glob, WebFetch, WebSearch. No shell, no writes |
| Read-only work that needs a shell: git history, public GitHub (`gh-public`, a shallow clone into temp), `curl` GET | `researcher` | Adds Bash, held to a read-only allowlist by the policy hook. No interpreters, no authenticated `gh` |
| Review, audit, cross-file consistency | `reviewer` | Read, Grep, Glob. You run the tests |
| Change files | `writer`, with `isolation: "worktree"` **on the Agent call** | Everything, inside its own worktree and branch. Commits, never pushes |
| A long build, a second opinion, or anything about Codex itself | `codex-delegate run` | Pinned Sol or Terra, workspace-write sandbox, memory cap, schema report |

- Use `general-purpose` only when no role fits, and say why in the brief. The three uses
  that have no role today:
  - Workflow agents that read sources and write output files (vetting-sources);
  - hq cross-home dispatch, where the target is another home;
  - messaged persona readers (staged-reader-review).

  Read-only work belongs to Explore, researcher or reviewer, and changes belong to writer.
  In the 2026-09-29 evaluation, all 5 general-purpose subagents that misbehaved had read-only
  briefs (4 were reviews or audits).
  general-purpose runs under the same sandbox and policy as every delegated agent (section 1b).
- A writer spawned without `isolation` on the call is denied by `agent-spawn-guard`. With
  agent teams on, a named spawn would otherwise start as a teammate in the main checkout,
  and the writer's frontmatter isolation is ignored.
- **One writer at a time.** Readers, researchers and reviewers can run in parallel. Run
  two writers only when their files are disjoint and you are the named merge owner.

## 1b. What no delegated agent can do

**Enforcement.** Claude Code's Bash sandbox is on for the whole session, and a policy hook
(`skills/delegation/policy.toml`) runs on every tool call a subagent or teammate makes. The
main thread is never policed; its retry outside the sandbox goes through your normal
permission flow.

**Every delegated agent:**
- **Stays in the sandbox:**
  - `dangerouslyDisableSandbox` is denied;
  - so is every `excludedCommands` entry, which covers `gh`, `git push/fetch/pull`, `codex`,
    `codex-delegate`, `claude`, `tmux` and `delegation-ledger`.
- **Can't reach authenticated GitHub.** `~/.config/gh` is unreadable inside the sandbox, so
  there is no push and no private-repo read. That holds whatever form the command takes.
  Public GitHub is available through `gh-public` and https clones.
- **Can't run destructive git.** reset, rebase, revert and clean are denied, as are a checkout
  or switch that discards, branch or tag deletion, stash drop/clear/pop, worktree changes and
  config writes.
- **Can't use aliases or functions:** `gp` is denied; `git push` is spelled out.
- **Can't use MCP write tools** (only the reads listed in policy.toml).
- **Can't send data over HTTP:** only GET or HEAD.
- **Can't write** Claude Code, shell, git or enforcement config.
- **Can't read credential files** or `/proc`, and can't Grep a directory that contains one
  (`~`, `~/.config`, `/`). Brief a narrower search root.
- **Can't `rm -r` outside its root** or temp.
- **Can't run past its deadline:** past its role's stop time, only the report path is
  allowed: the handback, SendMessage, and ToolSearch to load SendMessage (§4).

**Writers** also can't write outside their worktree: file tools, redirects, `cd`,
`git -C`. They can still read the main checkout. A computed-path subprocess write into the
main checkout can't be stopped; `delegation-ledger audit` flags it.

**When a denial arrives,** it names a rule and an intent. The agent reports it in
`blocked_actions` with that intent. If the work really needs it, you run it yourself in the
main thread. Your `git push` from another directory (`git -C x push`) doesn't match the
exclusion, so it fails on the missing credential; retry it outside the sandbox.

**Subagent or teammate?** A subagent, almost always. Don't pass `name`: a named spawn
silently becomes an agent-team teammate, so the spawn guard denies it. To talk to a subagent
again, SendMessage the id its spawn returned. A subagent's result returns as a notification,
and Claude Code aborts one that makes no progress for 10 minutes
(`CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`), though a single long tool call doesn't trip it.
Teammates report through idle notifications and can stay silent far longer: they accounted for 10 of
the 11 stalls in our eval.

A team earns its place only when agents must work together live:
- interlocking interfaces, where each side's shape depends on the other's;
- an adversarial investigation, where one agent attacks another's claims;
- dedup across a wide fan-out, where agents must claim items as they go.

Then name each spawn with the `team-` prefix (`policy.toml` `[spawn] team_prefix`), and the guard
lets it through. A writer still needs `isolation` on the call, and an isolated spawn isn't a
teammate, so a team can't include a writer; its changes go through you. Otherwise, you broker: a
subagent that needs another reports `partial` and names what it needs, and you resume the other
one through SendMessage.

## 2. Write the brief

Copy `BRIEF.md` (next to this file) and fill every section. The sections that matter most:
- the **artifact path**, which the agent writes as it goes, so a crash loses nothing;
- the **scope** in prose, for the agent's judgment;
- the **stop rule**, so a denial turns into a `blocked` report instead of a workaround;
- for writers, the **verification command**.

Keep the standing hard-boundaries block as written.

## 3. Check what comes back

Every role ends its reply with a fenced JSON block matching `report.schema.json`:
`status`, `summary`, `artifacts`, `blocked_actions`. The ledger records whether that block
validated (`report_ok`).

- **Missing or invalid block:**
  - For our four roles, `report-check` already sent it back up to twice. A report that
    reaches you invalid had three tries, and the ledger records `report_ok: false`.
  - A `team-` teammate's reports aren't checked (its stops fire per message), and neither
    are other types'. Ask once (SendMessage to its id).
  - Don't guess the status from the prose.
- **`blocked`:** each entry names an intent, and the intent decides what you do next.
  - `hard_stop`: drop it.
  - `use_alternative`: consider the named alternative.
  - `scope_down`: accept the smaller scope, or not.
  - `manual_only`: hand it to Hayden.
  - `stop_and_explain`: you decide.

  Never re-spawn the same brief hoping the denial goes away.
- **`partial` or `failed`:** read the summary before retrying, and retry at most once with
  a changed brief.
- **A `deadline` stop:** the agent ran past its role's budget for this activation, and every
  tool but the report path was denied (`[subagent-policy] deadline (stop_and_explain)`). Read
  its partial report first. Then resume it through SendMessage with a narrower brief, which
  starts a new activation with a fresh budget, or take the rest over yourself.
- **Writer:** review the diff on its branch (`artifacts[0]` is `branch@sha`), run the
  verification yourself, and merge single-threaded.
- **Reader:** if its output must survive this session, write the report to the artifact
  path yourself. Readers have no write tools.

## 4. Liveness and recovery

- **On any silence, run `delegation-ledger watch` before guessing.** It prints one line per
  live delegation, with what each is doing (`in Bash 12 min`, `running`, `finishing its turn`)
  and a `⚠` past a threshold. `delegation-ledger open` adds the evidence behind each verdict, and
  the orphans. Both run outside the sandbox as bare commands (`delegation-ledger` is in
  `excludedCommands`). A piped or chained call stays sandboxed, where no session pid is
  visible: it warns on its first line and calls each session `unknown`.
- `delegation-ledger audit` checks that enforcement still binds:
  - the policy hook saw every agent that used tools;
  - no writer's run coincided with a main-checkout change;
  - which reports failed the contract;
  - the denials.

  A session start runs it once a day and shows a warning once; run it yourself any time.
  `delegation-ledger sandbox-denials` lists the hosts and paths the sandbox refused, which feed
  `sandbox.network.allowedDomains`.
- `delegation-ledger audit --monthly` adds a month of usage (role shares, minutes per
  activation, the longest calls and silences) against `[deadline]` and `liveness.toml`, for
  retuning; `due` asks for it monthly. After a probe run by hand in a live session,
  `delegation-ledger exclude --id <id> --why probe` keeps it out of those numbers.
- **After a Claude Code upgrade,** the first session runs the quick canary in the background:
  the unit tests, the sandbox posture, and the strings our hooks read from the binary. A
  failure shows in the session-start line, which only Hayden sees. Run `delegation-ledger due`
  to see what is pending, including the dated items in `due.toml`. When it says the full
  canary is due (weekly, once the version has moved), run `delegation-ledger canary` outside
  the sandbox and with `run_in_background`: it takes about 6 minutes, and a slow run can pass
  the 10-minute foreground limit.
- `delegation-ledger open` lists delegations whose latest event isn't a stop. Each row
  shows its evidence:
  - whether the session is alive;
  - how long this activation has run (a resume or a teammate's next message starts a new one);
  - the newest transcript entry and how old it is;
  - how many tool calls are still open.

  It suggests; it doesn't decide.
- **Reading a verdict:**
  - `in <Tool> N min` means a call is in flight (a pending permission prompt shows here too).
    Past `tool_min` it adds a `⚠`: a long call, or a stuck one. Check it.
  - `running` means no call is open and the agent wrote to its transcript recently. Past
    `silent_min` with no entry, it says `⚠ ask it for status`.
  - The thresholds live in `skills/delegation/liveness.toml`, per kind (subagent, teammate,
    codex). A broken file falls back to the defaults, and `open` and `watch` print a warning
    first.
- **Every activation has a deadline,** a nudge time and a stop time per role, in
  `skills/delegation/policy.toml` `[deadline]` (the numbers live there; a role without its own
  entry gets `default`).
  - Past the nudge, the agent's next successful call carries one reminder to report
    (a `nudge` row in `delegation-ledger tail`).
  - Past the stop, every tool except SubagentHandback, SendMessage and ToolSearch is denied,
    so the agent hands back `partial` (see §3).
  - A long call that is already running finishes first. A SendMessage resume or a teammate's
    next message starts a new activation, with a fresh budget.
  - An agent that loops on its tools never trips a `⚠`; the deadline is what stops it.
- A **silent agent** is usually working, not dead. A `team-` teammate can sit idle between
  messages, and any agent can sit in one long tool call, which the stall timer doesn't
  abort. A `⚠` is a reason to look, not a verdict: ask it for status before you assume
  otherwise.
- **No delegated agent ends its turn while a background command runs.** Claude Code never
  wakes it when the command finishes, so it loses the result, and `open` can't flag it. A
  long command runs in the foreground (up to the Bash tool's 10-minute limit). A longer one
  runs in the background, and the agent waits on its output before reporting. `BRIEF.md`'s
  Budget section says so; keep that line.
- **Your own wait that may outlast 30 minutes goes through `delegation-ledger wait`.** A
  background Bash command stops at its timeout (30 minutes by default, 2 hours at most), and the
  wake-up note then says not to restart it. Launch the waiter as a bare command with
  `run_in_background` and `timeout: 7200000`: `delegation-ledger wait --pid <pid>` (or `--file`,
  `--log <path> --done <regex>`, `--codex <run_id>`). Before it polls, it prints a line naming
  the watch and the re-arm command. It exits 0 done, 1 failed, 2 stale. At 75 it prints a re-arm
  line: run exactly that, not the original command (though a rerun of the same wait takes the
  same watch over). The watch guard blocks your stop once when a watch has lapsed with no
  waiter, its job ended (done, failed or stale) with no waiter to tell you, or a background
  command was killed at its time limit. After that one block, a lapse goes quiet: a later stop
  lets you through, Hayden sees one warning, and nothing more comes until its job ends, however
  it ends, which blocks once more. So re-arm or drop it when it blocks. After a `/clear`, your
  first stop blocks once again on each lapse from before it. To stop watching,
  `delegation-ledger wait --drop <id>`.
- **After a crash or restart,** run `delegation-ledger open --hours 24`.
  - For each orphaned agent, look at its artifact path and redo only the unfinished part.
  - Its `watches:` block lists every unresolved watch, however old, and the ones that ended
    while no Claude process listened. One that needs re-arming (its waiter is dead, or alive
    but its exit reaches nobody) shows its `--resume` command: run it, or drop the watch. For
    an ended one, check the result.
  - In a session you continued (`claude --continue`), the watch guard blocks your first stop
    once for each watch the crash left: a waiter that still runs (its exit won't reach you, so
    re-arm it), a lapse (even one acknowledged before the crash), or a job that ended while
    nobody listened (check the result).
  - Hayden, not you, sees the session-start line. It names every unresolved watch whose
    waiter's exit reaches nobody, at each start, and once, each watch that ended while no
    Claude process listened. If they pass one on, handle it the same way.
  - For Codex, run `codex-delegate status`. A running run whose wrapper is gone names the
    `delegation-ledger wait --resume` that re-arms its watch, or, with no watch, says to finalize
    it once it ends. `codex-delegate resume <run_id>` continues an ended run, and finalizes its
    last turn first if that has no stop row.

## 5. Codex runs

**Always launch `run` and `resume` with the Bash tool's `run_in_background` and `timeout:
7200000`.** A foreground Bash command is stopped after 10 minutes, and a Codex run takes longer.
Before Codex starts, the wrapper prints a launch line with the run id and its watch id. It
waits as that watch's waiter, and its exit notification wakes you when the run ends, so there
is no need to poll.

A run can outlast the Bash tool's 2-hour cap. The wrapper exits first: at `--max-wait` (110
minutes) it prints the re-arm command and exits 75, and Codex keeps running. Run the command it
printed, in the background with the same timeout; that waiter finalizes the run once Codex
ends. If the wrapper is killed anyway, Codex keeps running too (it writes its own event log in
its own session), and the watch guard blocks your next stop with the same re-arm command.
If Codex has ended by then with nobody to finalize it, that block says to run
`codex-delegate finalize <run_id>` instead.
`status` says where a run is, and `finalize` records the result by hand.

```bash
codex-delegate run --model sol --dir ~/some/repo --brief brief.md [--network] [--timeout 3h]
codex-delegate status              # verdict with evidence, phase, exit/report/audit results
codex-delegate resume <run_id> --prompt fix.md
codex-delegate finalize <run_id>   # a run whose wrapper died: report check, audit, stop row
codex-delegate audit <thread_id>   # every model the thread and its sub-agents used
```

- **Models:** Sol or Terra only; the wrapper refuses anything else before launch. Use Terra
  for fetch-and-summarize.
- **Output:** everything lands in `<dir>/.codex-delegate/<run_id>/`: `report.json`,
  `events.jsonl` and `stderr.log`.
- **Exit codes:**
  - 0: ok;
  - 1: Codex failed (its own code is `rc` in the summary);
  - 2: refused, or bad usage (a resume while Codex still runs, too);
  - 3: the model audit failed;
  - 4: the report is missing or invalid;
  - 5: stopped waiting with its watch dropped or taken over; Codex keeps running;
  - 75: still running: re-arm with the printed command;
  - 124: timed out;
  - 143: killed by SIGTERM or SIGHUP while Codex ran; Codex keeps running, and the watch
    guard's next block prints the re-arm command.
- **Scope:** send Codex only the work it does better, such as anything about its own
  configuration. Claude does the rest.
