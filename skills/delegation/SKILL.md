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
  In the 2026-09-29 evaluation, every misbehaving general-purpose agent was a read-only review.
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
    `claude` and `tmux`.
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
- **After a Claude Code upgrade,** the first session runs the quick canary in the background:
  the unit tests, the sandbox posture, and the strings our hooks read from the binary. You hear
  about it only if it fails. When the session-start line says the full canary is due (weekly, once
  the version has moved), run `delegation-ledger canary` outside the sandbox and with
  `run_in_background`: it takes about 5 minutes, and a slow run can pass the 10-minute
  foreground limit. `delegation-ledger due` shows what is
  pending, including the dated items in `due.toml`.
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
    codex). A broken file falls back to the defaults, and `open` prints a warning first.
- A **silent agent** is usually working, not dead. A `team-` teammate can sit idle between
  messages, and any agent can sit in one long tool call, which the stall timer doesn't
  abort. A `⚠` is a reason to look, not a verdict: ask it for status before you assume
  otherwise.
- **No delegated agent ends its turn while a background command runs.** Claude Code never
  wakes it when the command finishes, so it loses the result, and `open` can't flag it. A
  long command runs in the foreground (up to the Bash tool's 10-minute limit). A longer one
  runs in the background, and the agent waits on its output before reporting. `BRIEF.md`'s
  Budget section says so; keep that line.
- **After a crash or restart,** run `delegation-ledger open --hours 24`.
  - For each orphaned agent, look at its artifact path and redo only the unfinished part.
  - For Codex, run `codex-delegate status`, then `codex-delegate resume <run_id>`.

## 5. Codex runs

**Always launch `run` and `resume` with the Bash tool's `run_in_background`.** A foreground Bash
command is stopped after 10 minutes, and a Codex run takes longer. The exit notification wakes
you, so there is no need to poll. If the wrapper does get killed anyway, Codex keeps running
(it writes its own event log in its own session). `status` then says so, and `finalize`
records the result once Codex ends.

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
  - 2: refused, or bad usage;
  - 3: the model audit failed;
  - 4: the report is missing or invalid;
  - 124: timed out.
- **Scope:** send Codex only the work it does better, such as anything about its own
  configuration. Claude does the rest.
