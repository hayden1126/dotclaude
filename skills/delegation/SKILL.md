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

**Subagent or teammate?** Default to a subagent. A subagent's result returns as a
notification, and Claude Code aborts one that makes no progress for 10 minutes
(`CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS`). Use a teammate only when the agents must talk to
each other while they work. Teammates report through idle notifications and can stay silent
far longer.

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
  - For other types, ask once (SendMessage to its id).
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

- `delegation-ledger audit` checks that enforcement still binds:
  - the policy hook saw every agent that used tools;
  - no writer's run coincided with a main-checkout change;
  - which reports failed the contract;
  - the denials.

  Run it after a Claude Code upgrade. `delegation-ledger sandbox-denials` lists the hosts
  and paths the sandbox refused, which feed `sandbox.network.allowedDomains`.
- `delegation-ledger open` lists delegations whose latest event isn't a stop. Each row
  shows its evidence:
  - whether the session is alive;
  - how many minutes old the transcript is;
  - what its last entry was.

  It suggests; it doesn't decide.
- A **silent teammate** is usually working, not dead. Ask it for status before you assume
  otherwise.
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
