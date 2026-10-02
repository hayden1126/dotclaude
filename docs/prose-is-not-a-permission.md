# Prose Is Not a Permission

*What 384 delegated agents taught me about keeping Claude Code subagents in scope.*

<!-- HERO IMAGE: one wide image above the fold. Brief: a key on a hook beside a closed door,
     or a sticky note reading "please don't" next to a padlock. Medium crops to about 2:1. -->

You can ask a house-sitter not to open the wine cellar. Or you can keep the key. Both usually
work. Only one still works on the day they forget what you said.

I learned this from a code reviewer. It was a Claude Code subagent, and its brief was clear:
read-only, create nothing. It wrote a Python script and ran it, which started the exact job the
brief was written to prevent.

The brief said no. The agent's tools said yes. The tools won.

That incident is this whole post in miniature. I went through 384 agents I'd delegated to in late
September, worked out why they drifted and why they seemed to stall, and rebuilt how delegation
works on my machine. The fix wasn't better wording. It was a rule about which jobs belong to words
and which belong to the machine.

## Two Complaints, 384 Agents

I had two complaints. Delegated agents **drifted**: they did more, less or other than asked, or went
somewhere their brief said not to. And they **stalled**: they went quiet and seemed never to report
back.

Before fixing either, I wanted numbers. Claude Code was close to its weekly limit, so I had Codex,
OpenAI's coding agent, analyze the transcripts of the Claude Code agents I'd delegated to from
September 19 to 29. Transcripts can hold private email and client text, so one rule covered the
data: a single script, `extract.py`, reads them and writes out metadata plus short, capped excerpts,
and the analysis reads only that.

The run itself taught me two things. First, a restart killed it partway through, and what survived
was what it had already written to disk. So every brief for an agent that writes now names an
artifact path it fills as it goes.

Second, two of its rules lived only in prose, which is the weakness it was measuring: use only the
two models I'd approved (`gpt-5.6-sol` or `gpt-5.6-terra`), and the data rule. They held because
Codex followed them, not because anything enforced them. Codex now runs through a wrapper that
enforces the model rule, refusing any other model at launch and checking every sub-agent's after the
run. The data rule is still prose.

Here's the whole count, so the numbers below add up. Of the 384 agents, 266 were subagents and 118
were *teammates*, members of an agent team (more on those below). The evaluation classed 357 as on
task, which means it detected nothing wrong, not that it verified success. The other 27 were twelve
that crossed a boundary, nine more that stalled, five that hit a permission denial (and still
reported), and one I stopped myself.

## Drift Is a Capability Problem

Twelve agents crossed a boundary. Seven drifted out of scope, three broke an explicit instruction,
and two drifted and also stalled. The reviewer from the opening is one of the three who broke an
instruction. Eight had briefs saying to work only in a git worktree, and used shared scratch space
or a sibling repo. The briefs never said whether scratch counted, and prose leaves gaps like that.

Every one of the twelve had its scope only in prose, and every one held full Bash. Bash alone
doesn't predict drift: it's common (general-purpose agents and the built-in Explore all have it),
and plenty of agents held it and stayed in scope. It's the means: the brief asked, the toolset
allowed, and the toolset decides.

The breakdown by type is blunter. Counting teammates by the role they were spawned as, eleven of the
twelve were *general-purpose* agents, the do-anything type: five subagents and six teammates. The
twelfth was the built-in *Explore*, a subagent, which forbids writes in its prompt but keeps Bash.

Of the 266 subagents, 118 were general-purpose (the same number as the teammates, by coincidence).
Five of those 118 crossed a boundary, against one of the other 148. And writing wasn't where they
failed. Most of the 118 changed things: 47 edited files, and about 45 more ran shell commands that
do, while fewer than a quarter only read. Yet all five that misbehaved had read-only briefs, and
four of them were reviews or audits.

Claude Code's [permissions docs](https://code.claude.com/docs/en/permissions) show why a deny rule
can't fix this: path rules don't apply to arbitrary subprocesses. An agent that can run `python3 -c`
can write anywhere its process can. An OS sandbox does reach the subprocess, but its limits are per
session, so it can't tell a reader from a writer.

So a read-only agent shouldn't be asked to leave Bash alone. It shouldn't have an open shell.

## Most Stalls Were Silence

The first pass of the evaluation found one stall. That didn't match what I'd seen, and a review
of the run found the mistake. It had treated *teammates* (members of an agent team, which report
through messages and idle notifications) like *subagents*, which return a result. It never read
the teammates' message channel.

Counted properly, there were 11 stalls, and 10 were teammates: 10 of 118 teammates (8.5%), against 1
of 266 subagents (0.4%). The two aren't defined the same way. A subagent stalled if it ended with no
final text. A teammate stalled if it took more than 30 minutes to answer a follow-up from the lead,
which is my own test rule, not a guarantee: at 15 minutes, 19 teammates fail it, and at 45, only 4.
All 118 teammates also came from three sessions, so read 8.5% as three sessions' worth, not a
general rate.

The ten teammates weren't lost. Every teammate eventually messaged the lead or finished a turn,
which sends the lead an idle notification. What looked like a stall was silence: 34 to 520 minutes
before a teammate answered a follow-up. The subagent's report, though, really was lost.

Teammates also run long. A teammate ran a median of 17 minutes, with a p90 of 172, against 3.8 and
13.2 for subagents. From the outside, an hour of silence looks the same whether the agent is working
or dead.

So what did all those teams buy me? Almost nothing. A second count the next day, from the team
config files on the machine rather than the eval's transcripts, found 57 teams and 89 teammates. The
two sources don't match (89 here, 118 in the transcripts), but they agree on the pattern. Every team
was implicit, created by a named spawn rather than on purpose. Of their 308 messages, 293 went to
the lead and 13 were reports passed between nested agents. Only 2 were peers coordinating, and
that's the one thing a team adds: reporting to the lead is what a subagent does anyway.

The accident has a cause. With agent teams on (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`), a spawn
from the main conversation with a `name` doesn't start a subagent. It starts a teammate, unless the
call forks the conversation or asks for its own worktree (`isolation`), as the [sub-agents
docs](https://code.claude.com/docs/en/sub-agents) say. I hadn't noticed that every named spawn of
mine had become a teammate.

## One Rule

Both findings point the same way:

> **Prose for purpose and judgment. Deterministic enforcement for authority, acceptance, and
> liveness.**

*Authority* is what an agent can touch. *Acceptance* is whether its report is well formed: a status
and a summary the lead can read without guessing from prose. *Liveness* is whether it's still
working, and whether it stops. Prose is still the right tool for the why: the goal, the context, the
judgment calls. It's the wrong tool for the limits.

One constraint shaped the rest. A *hook*, a script Claude Code runs at a fixed point such as before
every tool call, knows an agent only by its `agent_id` and `agent_type`, and never sees its brief.
So scope can't be "this agent may only touch `src/auth`". It has to be coarse: the role's tools, its
working directory, and the session's sandbox. You could parse the brief out of the transcript, but
that layout is undocumented, so it would break silently on an upgrade.

## Four Layers, Each Covering What the Others Can't

The roles carry the authority. My own *Explore* (it overrides the built-in) and *reviewer* get no
shell at all. *researcher* gets a shell held to a read-only allowlist. *writer* can edit and run
commands, but only in its own git worktree, with one known gap. Then four layers bind them, in the
order a tool call meets them.

![A delegated agent's tool calls, left to right. Every call passes the policy hook; only Bash
enters the sandbox; the final report passes the report check; the ledger records starts, stops
and denials.](images/delegation-layers.png)
*Every call passes the policy hook, but only Bash enters the sandbox. The dashed path is the known
write escape, and only the audit flags it.*

**The policy hook** runs before every tool call any delegated agent makes, general-purpose agents
and teammates included. It applies each role's rules, and every denial names an intent, so the agent
knows whether to stop, scope down, or hand the step back. It holds a writer's file tools to its
worktree and temp, and it refuses a Bash call that asks to leave the sandbox or that would run
outside it. For the file tools and the MCP tools, it's the only gate: they never enter the sandbox.

**The Bash sandbox** is Claude Code's own, enforced by the OS. It confines writes to the project and
temp, hides credential files and filters the network by hostname. It binds a command in any form: an
alias, a script, a Makefile or `eval`. On my machine git authenticates through `gh`, so hiding
`~/.config/gh` (with `~/.ssh` and the other credential files) means no sandboxed command can
authenticate to GitHub, as long as no token is exported from the shell (see the limits).

**The report check** reads the final report of each of those four roles against a JSON schema, and
sends a malformed one back at most twice. It's the one layer that doesn't cover every agent:
teammates report per message, and general-purpose agents have no fixed report shape, so both skip
it. The hook and the sandbox still bind them.

**The ledger** records every start, stop, policy denial and report verdict, and an audit reads it
for whatever got through. The dashed path in the diagram is one reason it exists: a writer's
`python3 -c` can build a path into the main checkout. The hook can't read code, and the main
checkout sits inside the sandbox's write root, so only the audit flags it, after the fact.

The parts aren't new. Nothing I surveyed enforced per-agent scope, so I built a thin layer on
Claude Code's native controls and borrowed the pieces: the destructive-command rules from
[cc-safety-net](https://github.com/kenryu42/cc-safety-net), a bash parser from
[Parable](https://github.com/ldayton/Parable), a retry cap from
[breadcrumb](https://github.com/oscarthroedsson/breadcrumb). From evaluation to finished took
about three days.

## Test the Assumptions You Built On

The first version rested on assumptions nobody had tested live. So before adding anything, I ran
four probes. Do agents spawned by a Workflow script reach the policy hook? Does Claude Code's stall
timer, which aborts a subagent after 10 minutes without progress, catch a stuck one? Are the
ledger's stop rows with no matching start harmless? Is a teammate policed by its role? Two passed
and two failed, and running them turned up bugs none of them targeted.

The best one: **my test harness never isolated the code it was meant to test.** `claude -p` loads
your user settings, so the installed copy of every hook ran beside the copy under test. A
regression could pass because the old copy still enforced the rule. The fix is one flag:
`--setting-sources project,local`.

The two failures were quiet. A teammate's `agent_type` turned out to be its name, not its role, so a
teammate spawned as the strict researcher got the looser default rules; the policy now reads the
role from the teammate's metadata. And the stall timer didn't abort an agent inside one long call: a
100-second call finished under a 45-second test timer. Among the other bugs, a duplicated hook kept
resetting the report check's retry count, so it never gave up, and one agent was refused 18 times as
it tried to stop.

The docs are where you start, not what you rely on. If your safety depends on a behavior, probe the
behavior.

## A Looping Agent Looks Healthy

That stall-timer result changed the liveness design. If an agent can sit in one call far past the
timer, "time since the last event" isn't enough. So liveness now comes from the agent's transcript:
a tool call with no result yet is a call in flight, and every entry carries a timestamp. One
command, `delegation-ledger watch`, prints a line per live agent, like `in Bash 12 min`. This leans
on the transcript layout I called fragile above, but only on those two things, and the weekly live
run (below) checks that they still hold.

The harder case is the busy agent. A looping agent keeps calling tools, so no timer fires and
nothing looks wrong. That's why every role gets a time budget: a nudge, then a stop. The budget
restarts with each *activation*: a spawn, a resume, or a teammate's next message.

| Role | Nudge | Stop |
|---|---|---|
| Explore | 10 min | 20 min |
| researcher, reviewer | 20 min | 40 min |
| writer, everything else | 30 min | 60 min |

Past the stop, every tool is denied except the ones the agent needs to report. The check runs
between calls, so a call already running finishes first; an agent stuck in one long call shows up in
`watch` instead.

The nudges sit at 1.5 to 2.3 times the subagents' p90 of 13.2 minutes, with Explore's below it,
since I treat a search past 10 minutes as probably lost. A teammate in one long turn does hit the
stop. That's the intent: it hands back a partial report, and I resume it with a narrower brief.

The surprise was how agents read these messages. The first nudge said only how far the agent was
into its budget, and a test agent read it as the stop and quit. Now it names both marks. An agent
resumed after a denial took the resume as a retry of the step it had been told not to retry.

In both cases the agent acted on its reading of my message. The stop is enforced, but the message
that explains it is prose. So the wording is part of the mechanism; test it like code.

The stop also had a plain bug. It denied ToolSearch, which a teammate needs to load the tool it
reports with. The teammate called that tool without its schema, and the call went through.
ToolSearch is allowed past the stop now.

## Claude Code Ships Daily, So My Setup Has a Canary

All of this leans on Claude Code internals that change without notice. Versions 2.1.284 to
2.1.286 landed in three days. Some failures make no noise at all: an unknown field in an agent's
frontmatter is ignored, and so is a settings value of the wrong type. And without
`failIfUnavailable`, a sandbox that fails to start just... runs without one.

So the cheap check runs itself, and the expensive one asks. After each upgrade, a quick canary runs
in the background: the unit tests, the sandbox posture, and a check that the binary still has the
names my hooks depend on. A full live run, 65 checks in about six minutes, comes up as a weekly
reminder once the version has moved. Each full run starts about 15 headless sessions, and upgrades
land almost daily, so running it on every upgrade would cost too much. The string checks only prove
a name still exists; the live run is what proves the behavior.

## What This Still Doesn't Stop

Enforcement has edges, and I'd rather name them:

- **The policy can't read code,** so script bodies and interpreter code get past it. The sandbox
  bounds them, except for the dashed path above: a writer's computed-path write into the main
  checkout, which the audit flags and nothing prevents.
- **Secrets exported from your shell rc file** are in every sandboxed command's environment, a
  GitHub token included, which would undo the credential hiding above. The fix that holds
  everywhere, MCP servers and excluded commands included, is not exporting them.
- **The network filter matches hostnames,** so domain fronting is possible.
- **Some gaps are watched, not closed.** An agent inside one long call isn't stopped until the call
  ends; `watch` shows it. Teammates' and general-purpose agents' reports go unchecked.
- **A non-isolated agent's file tools aren't held to a root.** Only an agent in its own worktree is,
  and every writer is one, which is one more reason changes go to *writer* and reads to the
  read-only roles.
- **The evidence is thin.** Twelve failures is a small sample, the teammates came from three
  sessions, and there's no before-and-after yet.

## Your First Hour: Hardening Delegation

If you delegate in Claude Code, here's the order I'd go in.

**Minutes 0 to 10: take Bash away from readers.** Stop sending read-only work to general-purpose
agents. Which type Claude picks is still prose (say it in your CLAUDE.md), but once it picks a
read-only type, the tools hold. Define your own `Explore` (a user agent with that name overrides the
built-in) and a reviewer, each with only the tools that read. Put each in `~/.claude/agents/`, as
`reviewer.md` and so on; the text below the frontmatter is its prompt. My reviewer's frontmatter:

```yaml
---
name: reviewer
description: Read-only reviewer. Returns findings with path:line and evidence.
tools: Read, Grep, Glob
---
```

**Minutes 10 to 20: turn the sandbox on, safely.** Merge this into `~/.claude/settings.json`,
spelled exactly, because a misplaced key is ignored without a word:

```json
{
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "autoAllowBashIfSandboxed": false,
    "filesystem": {
      "denyRead": ["~/.config/gh", "~/.ssh", "~/.netrc", "~/.aws", "~/.git-credentials",
                   "~/.claude/.credentials.json"]
    },
    "excludedCommands": ["git push", "git push *", "git fetch", "git fetch *",
                         "git pull", "git pull *", "gh *"]
  }
}
```

`failIfUnavailable` stops a sandbox that can't start from failing open. `autoAllowBashIfSandboxed`
defaults to true, which auto-approves sandboxed commands and ends your Bash prompts; I keep mine.
The allowed network hosts start empty. The docs say a sandboxed command's first request to a new
host asks you; in my headless probes, with nobody to ask, it was refused. `network.allowedDomains`
lists the hosts it may reach either way.

With credentials hidden, your own `git push` and `gh` can't authenticate inside the sandbox, so
`excludedCommands` (honored in user or managed settings, never a project's) runs them outside it.
They run there with your credentials, behind your normal prompt unless an allow rule already
approves them, so keep the list short. The hook below keeps delegated agents off them. The
`denyRead` list is part of mine; add the token files your own tools keep.

Restart Claude Code to apply it all. If it then won't start, the sandbox can't run on your machine:
on Linux and WSL2 it needs `bubblewrap` and `socat`, and `/sandbox` shows what's missing. Setting
`enabled` to false gets you back in, with no sandbox at all, so fix the cause before you delegate
again.

**Minutes 20 to 30: police what the sandbox can't see.** The file tools run outside it: in a live
probe, Grep read `/proc/self/environ`, which is Claude Code's whole environment. Add a
`PreToolUse` hook that acts only when the input carries an `agent_id` (a delegated agent) and
denies five things:
- the file tools on credential paths and `/proc`;
- a Grep rooted at any directory that holds a credential file, such as `~`, `~/.config` or `/`,
  since Grep searches hidden files;
- the file tools writing under `~/.claude`, where your settings and hooks live;
- any Bash call that sets `dangerouslyDisableSandbox`, which otherwise takes the command out of the
  sandbox, behind a permission prompt;
- any Bash call that starts with one of your excluded commands, which run outside the sandbox with
  your credentials.

Here's a minimal version. Save it as `~/.claude/hooks/deny-delegated.py`, make it executable, and
register it as a `PreToolUse` command hook in the same settings file, beside `sandbox`:

```python
#!/usr/bin/env python3
"""PreToolUse hook: deny five risky moves, for delegated agents only."""
import json
import os
import sys


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))
    sys.exit(0)


def forms(p):
    """A path as written (normalized) and with symlinks resolved."""
    return {os.path.normpath(p), os.path.realpath(p)}


def under(p, root):
    return p == root or p.startswith(root.rstrip("/") + "/")


try:
    call = json.load(sys.stdin)
    if "agent_id" not in call:  # the main thread: leave it alone
        sys.exit(0)
    tool, args = call.get("tool_name"), call.get("tool_input") or {}
    home = os.path.expanduser("~")
    raw = (args.get("file_path") or args.get("notebook_path") or args.get("path")
           or ("." if tool == "Grep" else ""))
    paths = forms(os.path.join(call.get("cwd", "."), os.path.expanduser(raw))) if raw else set()
    secrets = set().union(*(forms(home + s) for s in (
        "/.ssh", "/.aws", "/.config/gh", "/.netrc", "/.git-credentials",
        "/.claude/.credentials.json")))
    config = forms(home + "/.claude")
    excluded = ("git push", "git fetch", "git pull", "gh ")

    if tool == "Bash" and args.get("dangerouslyDisableSandbox"):
        deny("stop: delegated agents stay in the sandbox")
    if tool == "Bash" and args.get("command", "").lstrip().startswith(excluded):
        deny("hand back: the lead runs commands that leave the sandbox")
    if any(p.startswith("/proc") or under(p, s) for p in paths for s in secrets):
        deny("stop: credential path")
    if tool == "Grep" and any(under(s, p) for p in paths for s in secrets):
        deny("scope down: search a root that holds no credentials")
    writes = tool in ("Write", "Edit", "NotebookEdit")
    if writes and any(under(p, c) for p in paths for c in config):
        deny("stop: delegated agents don't write Claude Code's config")
except Exception:
    deny("stop: the hook failed, so it fails closed")
```

```json
"hooks": {
  "PreToolUse": [
    {"matcher": "*", "hooks": [{"type": "command", "command": "~/.claude/hooks/deny-delegated.py"}]}
  ]
}
```

It's a starting point, not a policy: it compares strings, so test it against the tricks you care
about. Mine parses the command and applies per-role rules:
[`subagent-policy`](https://github.com/hayden1126/dotclaude/blob/7ed72e9fbff07436645d785f7521190e761b47d7/skills/delegation/scripts/subagent-policy)
with its rules in
[`policy.toml`](https://github.com/hayden1126/dotclaude/blob/7ed72e9fbff07436645d785f7521190e761b47d7/skills/delegation/policy.toml).

**Minutes 30 to 40: stop accidental teams.** If you don't use agent teams, turn them off: remove
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` from your environment and from your settings' `env` block. If
you do use them, telling Claude not to pass `name` is prose. The key is a `PreToolUse` hook on
`Agent|Task` that denies a named spawn; mine is
[`agent-spawn-guard`](https://github.com/hayden1126/dotclaude/blob/7ed72e9fbff07436645d785f7521190e761b47d7/skills/delegation/scripts/agent-spawn-guard).

**Minutes 40 to 50: move secrets out of your shell.** Keep them in a file no shell sources. Put that
file in `denyRead` and in the hook's credential paths, and hand each MCP server only the variables
it needs, through the `env` block in its config.

**Minutes 50 to 60: test your hooks in isolation.** The quick test pipes a sample call into the
hook, as you would with the one above, and checks the decision. For a live test, run `claude -p
--setting-sources project,local` in a fixture project, so your installed hooks can't mask a
regression; the fixture's own `.claude/settings.json` has to carry the hook and settings under test,
except `excludedCommands`, which a project can't set, so pass those with `--settings`. And pin
settings names and types in a test (assert that `sandbox.failIfUnavailable` is `true`, say), because
wrong ones are ignored without a word.

That's an hour. It won't make an agent trustworthy. It makes the untrustworthy moves fail loudly.
The hour covers authority. Acceptance and liveness (the report check and the budgets), and the audit
that catches what gets through, take longer; they're in the repo.

## Keep the Key

Prose still matters. It's how an agent knows why, and it's what the agent falls back on when the
brief runs out. But a "don't" in a brief is a request. The tools are the permission.

Tell the agent why. Keep the key.

The design, the verified facts and the tests are in my [dotclaude
repo](https://github.com/hayden1126/dotclaude/tree/7ed72e9fbff07436645d785f7521190e761b47d7), with
the full write-up in
[docs/delegation.md](https://github.com/hayden1126/dotclaude/blob/7ed72e9fbff07436645d785f7521190e761b47d7/docs/delegation.md).
In a month the ledger will have enough data to retune the budgets, and I'll find out whether that
table had the right numbers.