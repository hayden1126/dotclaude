# Prose Is Not a Permission

*What 384 delegated agents taught me about keeping Claude Code subagents in scope.*

<!-- HERO IMAGE: one wide image above the fold. Brief: a key on a hook beside a closed door,
     or a sticky note reading "please don't" next to a padlock. Medium crops to about 2:1. -->

You can ask a house-sitter not to open the wine cellar. Or you can keep the key. Both usually
work. Only one still works on the day they forget what you said.

I learned this from a code reviewer. It was a Claude Code subagent, and its brief was clear:
read-only, create nothing. It wrote a Python script and ran it. The import kicked off the exact
workload the brief was written to prevent.

The brief said no. The agent's tools said yes. The tools won.

That incident is this whole post in miniature. I counted 384 agents I had delegated to, worked
out why they drifted and why they seemed to stall, and rebuilt how delegation works on my
machine. The fix wasn't better wording. It was a rule about which jobs belong to words and which
belong to the machine.

## Two Complaints, 384 Agents

I had two complaints. Delegated agents **drifted**: they did more, less or other than asked, or
stepped outside their permissions. And they **stalled**: they went quiet and seemed never to
report back.

Before fixing either, I wanted numbers. So I delegated the evaluation itself, to Codex, because
Claude Code was close to its weekly limit. Transcripts can hold private email and client text, so
the rule was strict: one script, `extract.py`, reads them and writes out a fixed list of fields,
and the analysis touches nothing else. It covered September 19 to 29.

The evaluation hit the problems it was measuring. A restart killed it partway through, and what
survived was what it had already written to disk. That's why every brief I write now names
an artifact path the agent fills as it goes.

Its other rules (use only `gpt-5.6-sol` or `gpt-5.6-terra`, and the data rule) held only because
Codex chose to follow the prose. Nothing enforced them. Codex now runs through a wrapper that
pins the model, the sandbox, a memory cap and a timeout.

## Drift Is a Capability Problem

Twelve agents crossed a boundary. Seven drifted out of scope, three broke an explicit
instruction, and two drifted and also stalled. Every one of the twelve had its scope in prose
while it held full Bash. Eight were told to stay in a git worktree and used shared scratch space
or a sibling repo instead.

The breakdown by type is blunter. Counting teammates by the role they were spawned as, eleven of
the twelve were *general-purpose* agents, the do-anything type: five subagents and six teammates.
The twelfth was the built-in *Explore*, which forbids writes in its prompt but keeps Bash. Most of
the 118 general-purpose subagents changed things: 47 edited files, and fewer than a third only
read. Yet the five that misbehaved all had read-only briefs, and four of them were reviews or
audits.

Claude Code's [permissions docs](https://code.claude.com/docs/en/permissions) show that even deny
rules can't stop this: the path rules don't apply to arbitrary subprocesses. An agent that can run
`python3 -c` can write anywhere its process can.

So a read-only agent shouldn't be asked to leave Bash alone. It shouldn't have Bash.

## The Stalls Weren't Stalls

The first pass of the evaluation found one stall. That didn't match what I'd seen, and a review
of the run found the mistake. It had treated *teammates* (members of an agent team, which report
through messages and idle notifications) like *subagents*, which return a result. It never read
the teammates' message channel.

Counted properly, there were 11 stalls, and 10 were teammates: 10 of 118 teammates (8.5%),
against 1 of 266 subagents (0.4%).

And they weren't lost. All 118 teammates eventually messaged the lead or went idle. What looked
like a stall was silence: 34 to 520 minutes before a teammate answered a follow-up. Teammates also
run long, with a median of 17 minutes and a p90 of 172, against 3.8 and 13.2 for subagents. From
the outside, an hour of silence looks the same whether the agent is working or dead.

(The 30-minute cutoff is my own test rule, not a guarantee. At 15 minutes, 19 teammates fail it;
at 45, only 4.)

So what did all those teams buy me? Almost nothing. A second count the next day, from the team
config files, found 57 teams, and every one was implicit. Of 308 teammate messages, 2 were real
coordination between peers. The rest went to the lead, or were nested agents passing reports back
and forth.

The accident has a cause. With agent teams on (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`), a spawn
from the main conversation with a `name` doesn't start a subagent. It starts a teammate, unless
the call is a fork or passes `isolation`
([sub-agents docs](https://code.claude.com/docs/en/sub-agents)). Every named spawn of mine had
silently become a teammate.

## One Rule

Both findings point the same way:

> **Prose for purpose and judgment. Deterministic enforcement for authority, acceptance, and
> liveness.**

*Authority* is what an agent can touch. *Acceptance* is whether its report is well formed.
*Liveness* is whether it's still working, and whether it stops. Prose is still the right tool for
the why: the goal, the context, the judgment calls. It's the wrong tool for the limits.

One constraint shaped the rest. A hook knows an agent only by its `agent_id` and `agent_type`,
and never sees its brief. So scope can't be "this agent may only touch `src/auth`". It has to be
coarse: the role's tools, its working directory, and the session's sandbox. You could parse the
brief out of the transcript, but that layout is undocumented, so it would break silently on an
upgrade.

## Four Layers, Each Covering What the Others Can't

The roles carry the authority. *Explore* and *reviewer* get no shell at all. *researcher* gets a
shell held to a read-only allowlist. *writer* can edit and run commands, but only in its own git
worktree. Then four layers bind them, in the order a tool call meets them.

![A delegated agent's tool calls, left to right. Every call passes the policy hook; only Bash
enters the sandbox; the final report passes the report check; the ledger records starts, stops
and denials.](images/delegation-layers.png)
*Every call passes the policy hook, but only Bash enters the sandbox. The dashed path is the known
write escape, and only the audit flags it.*

**The policy hook** runs before every tool call a delegated agent makes. It applies each role's
rules, and every denial names an intent, so the agent knows whether to stop, scope down, or hand
the step back. For the file tools and the MCP tools, it's the only gate: they never enter the
sandbox.

**The Bash sandbox** is Claude Code's own, enforced by the OS. It confines writes, hides credential
files and filters the network by hostname. It binds a command in any form: an alias, a script, a
Makefile or `eval`. On my machine git authenticates through `gh`, so hiding `~/.config/gh` (with
`~/.ssh` and the other credential files) means nothing inside the sandbox can authenticate to
GitHub.

**The report check** reads the final report of each of those four roles against a JSON schema,
and sends a malformed one back at most twice. Teammates and general-purpose agents skip it.

**The ledger** records every start, stop and denial, and an audit reads it for whatever got
through. The dashed path in the diagram is one reason it exists: a writer's `python3 -c` can build
a path into the main checkout. The hook can't read code, and the main checkout sits inside the
sandbox's write root, so only the audit flags it, after the fact.

The parts aren't new. Nothing I surveyed enforced per-agent scope, so I built a thin layer on
Claude Code's native controls and borrowed the pieces: the destructive-command rules from
[cc-safety-net](https://github.com/kenryu42/cc-safety-net), a bash parser from
[Parable](https://github.com/ldayton/Parable), a retry cap from
[breadcrumb](https://github.com/oscarthroedsson/breadcrumb). From evaluation to finished took
about three days.

## Test the Assumptions You Built On

The first version rested on assumptions nobody had tested live. So before adding anything, I ran
four probes against them, and they turned up bugs no probe was looking for.

The best one: **my test harness never isolated the code it was meant to test.** `claude -p` loads
your user settings, so the installed copy of every hook ran beside the copy under test. A
regression could pass because the old copy still enforced the rule. The fix is one flag:
`--setting-sources project,local`.

The rest failed as quietly. A duplicated hook made the report check loop, and one agent went
through 18 stops. A teammate's `agent_type` turned out to be its name, not its role, so a teammate
spawned as the strict researcher got the looser default rules. And Claude Code's stall timer
didn't abort an agent inside one long call: a 100-second call finished under a 45-second timer.

The docs are a hypothesis. If your safety depends on a behavior, probe the behavior.

## A Looping Agent Looks Healthy

That stall-timer result changed the liveness design. If an agent can sit in one call far past the
timer, "time since the last event" isn't enough. So liveness now comes from the agent's
transcript: a tool call with no result yet is a call in flight, and every entry carries a
timestamp. One command, `delegation-ledger watch`, prints a line per live agent, like
`in Bash 12 min`.

The harder case is the busy agent. A looping agent keeps calling tools, so no timer fires and
nothing looks wrong. That's why every role gets a time budget, which restarts each time the agent
is resumed: a nudge, then a stop.

| Role | Nudge | Stop |
|---|---|---|
| Explore | 10 min | 20 min |
| researcher, reviewer | 20 min | 40 min |
| writer, everything else | 30 min | 60 min |

Past the stop, every tool is denied except the ones the agent needs to report.

The surprise was how agents read these messages. The first nudge read like "66.1 min of this
activation's 30 min budget", and a test agent took it as the stop and quit. An agent resumed after a
denial took the resume as a retry of the step it had been told not to retry. A stopped teammate
couldn't even load the tool it reports with, because the stop denied that too; it got its report
out by calling the tool blind.

Agents treat your control messages as instructions. The wording is part of the mechanism, so test
it like code.

## Claude Code Ships Daily, So the Checks Run Themselves

All of this leans on Claude Code internals that change without notice. Versions 2.1.284 to
2.1.286 landed in three days. Some failures make no noise at all: an unknown field in an agent's
frontmatter is ignored, and so is a settings value of the wrong type. And without
`failIfUnavailable`, a sandbox that fails to start just... runs without one.

So the setup checks itself. After each upgrade, a quick canary runs in the background: the unit
tests, the sandbox posture, and a check that the binary still has the names my hooks depend on. A
full live run, 65 checks in about six minutes, comes up as a weekly reminder once the version has
moved. Running it on every upgrade would cost about 15 sessions a day. The string checks only prove
a name still exists; the live run is what proves the behavior.

## What This Still Doesn't Stop

Enforcement has edges, and I'd rather name them:

- **The policy can't read code,** so script bodies and interpreter code get past it. The sandbox
  bounds them, except for the dashed path above: a writer's computed-path write into the main
  checkout, which the audit flags and nothing prevents.
- **Secrets exported from your shell rc file** are in every sandboxed command's environment. The
  fix that holds everywhere, MCP servers and excluded commands included, is not exporting them.
- **The network filter matches hostnames,** so domain fronting is possible.
- **The evidence is thin.** The 118 teammates came from three sessions, and the 357 agents
  classed as on task are the ones where nothing was detected, not ones verified as successful.

## Your First Hour: Hardening Delegation

If you delegate in Claude Code, here's the order I'd go in.

**Minutes 0 to 10: take Bash away from readers.** Define your own `Explore`: a user agent with that
name overrides the built-in. Give readers and reviewers only the tools that read.

```yaml
---
name: reviewer
description: Read-only reviewer. Returns findings with path:line and evidence.
tools: Read, Grep, Glob
---
```

**Minutes 10 to 20: turn the sandbox on, safely.** In `~/.claude/settings.json`, spelled exactly,
because a misplaced key is ignored without a word:

```json
{
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "autoAllowBashIfSandboxed": false,
    "filesystem": {
      "denyRead": ["~/.config/gh", "~/.ssh", "~/.netrc", "~/.aws", "~/.git-credentials"]
    },
    "excludedCommands": ["git push", "git push *", "git fetch", "git fetch *",
                         "git pull", "git pull *", "gh *"]
  }
}
```

`failIfUnavailable` stops a sandbox that can't start from failing open. `autoAllowBashIfSandboxed`
defaults to true, which auto-approves sandboxed commands and ends your Bash prompts; I keep mine.
With credentials hidden, your own `git push` and `gh` can't authenticate inside the sandbox, so
`excludedCommands` (honored only in user settings) runs them outside it, behind your normal
prompt. Restart Claude Code to apply it. If it won't start, set `enabled` to false until the
sandbox works.

**Minutes 20 to 30: police what the sandbox can't see.** The file tools run outside it: in a live
probe, Grep read `/proc/self/environ`, which is Claude Code's whole environment. Add a
`PreToolUse` hook that acts only when the input carries an `agent_id` (a delegated agent) and
denies three things:
- the file tools on credential paths and `/proc`;
- a Grep rooted at `~`, `~/.config` or `/`, since Grep searches hidden files;
- any Bash call that sets `dangerouslyDisableSandbox`, which otherwise takes the command out of the
  sandbox, behind a permission prompt.

Mine is [`subagent-policy`](https://github.com/hayden1126/dotclaude/blob/7ed72e9fbff07436645d785f7521190e761b47d7/skills/delegation/scripts/subagent-policy) with its rules in
[`policy.toml`](https://github.com/hayden1126/dotclaude/blob/7ed72e9fbff07436645d785f7521190e761b47d7/skills/delegation/policy.toml).

**Minutes 30 to 40: stop accidental teams.** If agent teams are on, don't pass `name` to a spawn
unless you want a teammate.

**Minutes 40 to 50: move secrets out of your shell.** Keep them in a file no shell sources. Put that
file in `denyRead` and in the hook's credential paths, and hand each MCP server only the variables
it needs.

**Minutes 50 to 60: test your hooks in isolation.** Run hook tests with
`--setting-sources project,local`, so your installed hooks can't mask a regression. That also drops
your user-tier env and settings, so the test fixture has to carry what it needs. Pin settings names
and types in a test, because wrong ones are ignored without a word.

That's an hour. It won't make an agent trustworthy. It makes the untrustworthy moves fail loudly.

## Keep the Key

Prose still matters. It's how an agent knows why, and it's what the agent falls back on when the
brief runs out. But a "don't" in a brief is a request. The tools are the permission.

Tell the agent why. Keep the key.

The design, the verified facts and the tests are in my
[dotclaude repo](https://github.com/hayden1126/dotclaude/tree/7ed72e9fbff07436645d785f7521190e761b47d7),
with the full write-up in
[docs/delegation.md](https://github.com/hayden1126/dotclaude/blob/7ed72e9fbff07436645d785f7521190e761b47d7/docs/delegation.md).
In a month the ledger will have enough data to retune the budgets, and I'll find out whether the
numbers above were the right ones.
