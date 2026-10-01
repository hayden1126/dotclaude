# Delegation hardening

Delegated agents drifted out of scope and seemed to stall. This is the design that fixes it, what
ships, and what comes next. The skill that operators follow is `skills/delegation/SKILL.md`. This
doc holds the reasoning and the verified facts behind it.

## Principle and evidence

Prose covers purpose and judgment. Enforcement covers authority, acceptance and liveness. Scope is
**coarse**: an agent's reach comes from its role (its tools), its working directory and the
session's sandbox, and never from parsing its brief. Hook input identifies an agent only by
`agent_id` and `agent_type`, so a hook could not read a per-task scope even if we wanted it to.

The 2026-09-29 evaluation covered 384 agents over 10 days. Its data stays local in
`~/scratch/delegation-eval/` and is not in git, because it names agent IDs from other projects. It
found:
- **Drift:** 12 drift or instruction-violation cases. Every one was an agent given a scope in prose
  while it held full Bash.
- **"Stalls":** these were long, silent teammate turns (10 of 118 teammates went over 30 minutes), not
  lost reports. Ordinary subagents lost 1 report in 266.
- **general-purpose:** 118 general-purpose agents ran. 47 edited files, 35 ran mutating shell commands,
  and 36 were read-only. All 5 of its misbehaviors were read-only reviews that wrote scratch files or
  ran code.

## Layers

Each layer covers what the others can't.

1. **The Bash sandbox** is Claude Code's own: session-wide, OS-enforced, and for Bash only.
   - It confines Bash writes to the session repo, the Claude temp dir and the declared caches.
   - It hides credentials.
   - It filters the network by hostname.
   - It binds a command whatever form it takes: an alias, a script, a Makefile or `eval`.
2. **The subagent policy hook** is PreToolUse `*`, and it runs only when `agent_id` is present.
   - It denies leaving the sandbox.
   - It polices the file and MCP tools, which the sandbox never sees.
   - It applies each role's rules, and says why, with an intent.
   - It stops an agent that runs past its role's time budget, after the ledger hook has nudged
     it ("Deadline (A2)").
   - It catches the obvious forms; layer 1 catches the rest.
3. **The report check** covers acceptance. It sends a malformed report from one of our roles back
   to the agent at most twice.
4. **Observation.**
   - The ledger records every start, stop, denial and deadline nudge.
   - `audit` flags a hook that stopped seeing agents, and a writer run that coincided with a
     main-checkout change.
   - `sandbox-denials` lists what the sandbox refused.
   - The canary re-verifies all of this on a new Claude Code version, and a SessionStart check
     runs the cheap checks itself and reminds Hayden of the rest ("Stage 3", A4 and A5).

| Actor | Sandbox | Policy hook | Report check |
|---|---|---|---|
| Main thread (including `--agent`) | on, with the escape through the normal permission flow | not applied (the settings command exits before Python unless the payload's text contains `"agent_id"`; Python then exits at once) | n/a |
| Explore, reviewer | n/a (no Bash) | credential-read and MCP rules | yes |
| researcher | on, no escape | Bash **allowlist**; credential and MCP rules | yes |
| writer | on, no escape | default rules; root = `worktreePath` | yes |
| general-purpose, forks, Plan, plugin and Workflow agents | on, no escape | default rules; root = the project directory | no (their reports aren't JSON-bound) |
| in-process teammates | on, no escape | their role's rules (meta.json `customAgentType`), else the default rules | no (their stops fire per message) |

## What ships

| Piece | File | Enforces or persuades |
|---|---|---|
| `Explore`, overriding the built-in | `agents/Explore.md` | Enforces: Read, Grep, Glob, WebFetch and WebSearch only, on sonnet, CLAUDE.md skipped. The built-in keeps Bash and asks for read-only in prose only |
| `researcher` | `agents/researcher.md` | Enforces: its Bash runs on the policy's read-only allowlist |
| `reviewer` | `agents/reviewer.md` | Enforces: Read, Grep and Glob only |
| `writer` | `agents/writer.md` | Enforces: `isolation: worktree`, no Agent tool, and the policy's worktree root |
| Spawn guard | `hooks/agent-spawn-guard.sh`, `skills/delegation/scripts/agent-spawn-guard` | Enforces: denies a `writer` spawn without `isolation` on the call, and a named spawn without the `team-` prefix. Fails closed |
| Sandbox | `settings.json` `sandbox` | Enforces (OS): the write roots, `denyRead` (the credential barrier), `denyWrite` (the enforcement sources), and the network allowlist. `failIfUnavailable`, and `autoAllowBashIfSandboxed: false`, so Hayden's prompts stay as they were |
| Subagent policy | `hooks/subagent-policy.sh`, `skills/delegation/scripts/subagent-policy`, `skills/delegation/policy.toml` | Enforces: see "Subagent policy" below. Fails closed for the tools it polices |
| Report check | `hooks/report-check.sh`, `skills/delegation/scripts/report-check` | Enforces acceptance: a schema-invalid report is sent back twice at most. Fails open |
| Ledger | `hooks/delegation-ledger.sh`, `skills/delegation/scripts/delegation-ledger`, `skills/delegation/liveness.toml` | Observes: start and stop rows (`agent_type` is the resolved role; a teammate adds `name` and `teammate`), `report_ok`, denial rows, the main-checkout hash for a worktree agent; the per-agent liveness index (`agents/<id>.json`); `open` (the tool in flight and since when, thresholds in `liveness.toml`); `watch` (one line per live delegation, and a token like `2▶ 1⚠` for the tmux bar); `audit`; `sandbox-denials`. Persuades: the deadline nudge, one PostToolUse `additionalContext` per activation past the role's `nudge_min`, and a `nudge` row. Fails open |
| Canary and due checks | `hooks/delegation-due.sh`, `skills/delegation/scripts/delegation_checks.py`, `skills/delegation/due.toml` | Observes: `delegation-ledger canary` re-verifies enforcement on this Claude Code version; `due` runs the cheap checks at session start and shows Hayden what needs him. Fails open |
| Public GitHub client | `skills/delegation/scripts/gh-public` | GET-only access to api.github.com for delegated agents, optionally with a public-read token |
| Brief and report | `skills/delegation/BRIEF.md`, `report.schema.json` | Persuades (the brief); checks (the schema) |
| Codex wrapper | `skills/delegation/scripts/codex-delegate` | Enforces: model gate, sandbox, memory cap (via systemd-run when available, otherwise a warning), timeout, schema, and a recursive model audit |
| `worktree.baseRef: "head"` | `settings.json` | A writer's worktree branches from the current branch, not from `main` |
| `teammateMode: "in-process"` | `settings.json` | Pins the default: split-pane teammates are separate processes whose hook input has no `agent_id`, so the policy would never see them |

### Subagent policy

The rules live in `policy.toml`; the script only interprets them.

**Gate.**
- The settings command exits 0 unless the input's text contains `"agent_id"`. A main-thread call
  whose payload happens to mention it starts Python, which checks the real field and exits at once.
- Otherwise it runs `timeout 8 bash …/subagent-policy.sh || exit 2`, so a missing link, a crash or
  a hang blocks the call.
- Inside the script, a 5-second alarm denies before Claude Code's own hook timeout would let the
  call through.
- An exception denies a policed tool (shell, file, MCP), but allows a handback or a message, so a
  policy bug can't swallow a report.

**The sandbox must be on.** The hook merges the user, project, local and managed settings files, and
gives a delegated agent no Bash unless `sandbox.enabled` and `failIfUnavailable` are both true. A
repo that turns the sandbox off loses subagent Bash; the policy still applies.

**Default rules** (every delegated agent), each with a cc-safety-net intent:
- **The deadline,** checked first: past the role's `stop_min` for this activation, every tool
  except the report path (SubagentHandback, SendMessage, ToolSearch) is stop_and_explain
  ("Deadline (A2)").
- **The sandbox escape:** any truthy input key matching `/sandbox/i` is hard_stop.
- **Excluded commands:** an `excludedCommands` match is manual_only. The list is read live from the
  trusted tiers, as Claude Code reads it.
- **Parsing:**
  - The command is parsed with Parable, and every simple command is walked (lists, pipes,
    subshells, `$( )`, backticks, control flow).
  - A parse error is stop_and_explain, which also catches zsh glob qualifiers. `${(…)`, `$~` and
    `=(…)` are denied explicitly.
  - Wrappers are peeled: `env`, `command`, `exec`, `timeout`, `nice`, `nohup`, `xargs`, `find -exec`,
    `bash`/`sh`/`zsh -c` (recursively), and `eval` with a static argument.
  - A shell reading stdin (`… | sh`) and `source` (except `*/bin/activate`) are denied.
- **Command words** must resolve on PATH, be a path to an executable, or be a builtin. That denies
  oh-my-zsh aliases (`gp` = `git push`) and shell functions, and zsh `=git`.
- **Environment:** `GIT_*`, `LD_*`, `BASH_ENV`, `PAGER` and similar prefixes are denied (except
  `GIT_PAGER=cat`), and so is `git -c`.
- **git:**
  - reset, rebase, revert and clean are denied;
  - so are a checkout or switch that discards, restore without `--staged`, and branch or tag
    deletion;
  - so are stash drop/clear/pop, worktree changes, remote and config writes, and reflog or
    update-ref deletion;
  - so are `--no-verify`, `--output`, `--ext-diff` and the `ext::` transport;
  - an unknown subcommand is denied, which catches git aliases.
- **HTTP:** curl and wget are GET or HEAD only, and send no data.
- **rm:** `-r` outside the root, allowWrite and temp is denied; so are a dynamic or glob target of
  `-r`, git metadata, and `/` or home.
- **MCP:** only the read tools listed in `[mcp]`. A new MCP tool fails closed until it is listed.
- **Protected writes:** file tools and literal Bash targets are realpath-resolved, so symlinks count.
  The protected paths are:
  - `~/.claude`, the project's `.claude` (except `.claude/worktrees`) and `.mcp.json`;
  - git hooks and config;
  - shell rc files;
  - the live enforcement sources in `~/dotclaude`;
  - the ledger and the liveness index (`~/.local/state/dotclaude`), so an agent can't reset its
    own deadline clock.
- **Credential reads:** Read, Grep and Glob on the credential paths are denied (hard_stop), because
  those tools run outside the sandbox. The paths include `~/.secrets.env` and all of `/proc`: a
  file tool runs in Claude Code's own process, so `/proc/self/environ` is its whole environment
  (a live probe read it through Grep).
- **Credential searches:** a Grep rooted above an existing credential path (`~`, `~/.config`, `/`)
  is denied (scope_down). Grep searches hidden files recursively, so `Grep ghp_ ~` would read
  `~/.config/gh/hosts.yml`. Glob only lists names, so it isn't checked.

**Writer:**
- Its root is `meta.json`'s `worktreePath`, falling back to a cwd under `.claude/worktrees/`.
  Otherwise it is denied.
- File-tool writes must stay inside the worktree or temp.
- Bash write targets, `cd` and `git -C` into the session repo but outside the worktree are denied.
- Reads of the main checkout stay allowed.

**Researcher:** an allowlist.
- **Allowed:**
  - coreutils readers;
  - grep, rg and find without their exec, write or filter flags;
  - jq, `sed -n`, sort, uniq, diff;
  - read-only git and its list forms;
  - curl GET and `wget -O-` to stdout;
  - `gh-public`;
  - `git clone` of an https URL into the Claude temp dir;
  - `<program> --version|--help`.
- **Redirects** go only to `/dev/null`.
- **No interpreters.**

### Public GitHub for delegated agents (the credential barrier)

git authenticates through `gh auth git-credential` over HTTPS, and its token lives in
`~/.config/gh`. The sandbox's `denyRead` hides that directory. So nothing inside the sandbox can
authenticate to GitHub, whatever form the command takes: an alias, a Makefile or a test script.

The main thread's `gh` and git network commands are in `excludedCommands`. They run unsandboxed
through the normal permission flow, as they did before. Delegated agents are denied every excluded
command.

For public data:
- `gh-public` (GET only, api.github.com, REST and search);
- `curl`;
- `git clone` over https, which isn't excluded, so it stays sandboxed and credential-less;
- WebFetch.

Code search needs a token. A classic token with **no scopes** at
`~/.config/dotclaude/github-public-token` can read public data only, and it lifts the rate limit
from 60 to 5,000 requests an hour.

### Where enforcement stops (known gaps)

- **A real agent's `dangerouslyDisableSandbox` denial is not observed live.** The teammate probe
  declined to try it. The harness covers the rule (its `policy` case).
- **A writer's computed-path write into the main checkout.**
  - The sandbox's write root is the session's cwd, and a worktree lives inside it.
  - A live probe (2026-09-30) showed a worktree subagent writing the main checkout through
    `python3 -c` with a computed path. A plain `../../../` redirect worked too, until the
    policy's literal-path check.
  - Claude Code's own worktree check stopped neither.
  - The hook denies the literal forms. For the computed ones, the ledger hashes the main
    checkout's `git status` at the writer's start and stop, and `audit` reports a change. That is
    evidence, since the lead may have edited too.
- **What the policy can't see.** Script bodies, interpreter code, and an alias that shadows a real
  binary name are out of its sight. The sandbox, the credential barrier and the network filter
  bound them (cc-safety-net's residual risks RR-1 to RR-5).
- **Secrets in the shell environment.** A secret exported from a shell rc file is in Claude
  Code's environment, so every sandboxed command inherits it and a delegated agent's `env` prints
  it. Probed on 2.1.285 (2026-09-30):
  - `sandbox.credentials.envVars` with `mode: "deny"` blanks the variable in sandboxed commands
    only. Excluded commands and MCP servers run outside the sandbox and keep it.
  - Deny alone isn't enough when `~/.zshenv` sources a secrets file: the sandboxed zsh sources it
    again. The file must also be in `sandbox.filesystem.denyRead`.
  - The sandbox has its own PID namespace, so `/proc/<pid>/environ` of the parent isn't visible
    from Bash. The file tools are covered by the credential-read rule above.

  The fix that holds is to not export secrets at all. Keep them in a file no shell sources
  (`~/.secrets.env`, which the baseline's `denyRead` hides from sandboxed commands), and start
  each MCP server that needs one through a wrapper that reads the file and passes that server
  only the names it needs. A new secret is then protected by default, and no variable name
  appears in any settings file. hq's `bin/hq-mcp-env` is one such wrapper. An `envVars` deny list
  is the fallback; it names each variable, so it belongs in the private live settings, not this
  baseline.
- **A program the same command line creates is denied.** In `uv venv .venv && .venv/bin/python
  -c ...`, the policy checks `.venv/bin/python` before `.venv` exists, so it can't resolve it and
  denies it as `unknown-command`. Seen once in the live harness (2026-09-30), from a writer that
  chained its steps. Kept strict on purpose (Hayden's call): the denial now says the path doesn't
  exist yet and to run the creating step as its own Bash call first, instead of guessing at an
  alias.
- **Network filtering is by hostname only,** so domain fronting is possible.
- **A cloned repo's committed `sandbox.filesystem.allowWrite`** widens that repo's own sandbox
  (cc-safety-net RR-11). This is noted, not policed.
- **Hook timeout.** A hook timeout is non-blocking. The settings command's `timeout 8` and the
  script's 5-second alarm both deny first.
- **Teammates are checked by hand.** `-p` still can't create a teammate (2.1.286: a named spawn
  there runs as a plain subagent), so the live harness can't cover one. The teammate facts below
  come from a live session. A teammate's meta.json appeared about 0.5 s after its transcript
  began and before its first tool call; a first call that beat it would get the default rules.
- **A background command a subagent leaves running.** A subagent that backgrounds a command and
  ends its turn isn't flagged: its stop row takes it out of `open`, and SubagentStop's
  `background_tasks` can't say whose task is whose (it is session-wide, so A1 ignores it). Claude
  Code doesn't wake the agent when the task ends (probe, 2.1.286), so the result is lost to it.
  `BRIEF.md` tells agents not to end a turn with a background command running, and SKILL §4
  explains why.
- **Vault.** There is deliberately no vault read deny. A session-wide deny would break hq's vault
  routing and vault's own sessions, and Bash writes to vault from other sessions are already
  outside the write roots.

## Stage 3

Stage 3 makes the setup check itself instead of relying on someone remembering. It runs in steps,
Step 0 and then A0 to A6, planned in `~/.claude/plans/lets-move-on-to-refactored-pascal.md`. Step 0,
A0, A4, A5, A1, A3 and A2 are done.

**Step 0** came first because everything after it rests on assumptions Stage 2 made but never
tested live. It is four probes:
- P1: Workflow agents carry `agent_id`, so the policy hook sees them;
- P2: the stall timer aborts a subagent that stops making progress;
- P3: the ledger's unpaired rows are harmless;
- P4: a teammate is policed by its role.

Running them also turned up four bugs that no probe targeted.

### What Step 0 found

The probes:
- **P1: Workflow agents are policed.** In one probe run, a Workflow agent's hook input carried
  `agent_id` (with `agent_type: "workflow-subagent"`), and the policy denied its `git push`. That
  is one run, not a proof; the `workflow` case in the live harness re-runs it, and so does every
  full canary run (A5).
- **P2: the stall timer doesn't catch an agent inside one long tool call.** A 100-second call
  finished under a 45-second timer. So liveness (A1) must track how long a tool has been running,
  not only the time since the last event.
- **P3: the ledger's unpaired rows are not coverage gaps.** The stops without a start from 05:17Z
  to 06:24Z on 2026-09-30 were Claude Code's own helper agents, logged before the ledger learned to
  skip them (their `agent_type` is empty). The one general-purpose stop without a start belonged to
  an agent that began at 05:16:28Z, 30 seconds before the ledger's first row. A researcher's two
  stops were both real: its plain-text reply stopped it once, then Claude Code injected
  `[handback-send-enforce] Your report has not been delivered`, and it stopped again after
  `SubagentHandback`. The ledger's reader already keeps the latest row per agent (`fold`), so any
  count must use distinct agent ids, not stop rows.
- **P4: a teammate's `agent_type` is its name.** A `team-probe` spawned as `researcher` arrived as
  `agent_type: "team-probe"`. The policy saw it (its `agent_id` was present, and it denied the
  `git push`), but it applied the default rules, not the stricter researcher allowlist. The role is
  in meta.json's `customAgentType`, beside `taskKind: "in_process_teammate"`. The policy and the
  ledger now resolve the role through `delegation_common.agent_role`, and the ledger also records
  the teammate's `name`. This matters because A0 still lets a `team-` spawn through.

Found along the way:
- **The harness never isolated the code under test.** `claude -p` loads user settings, so the
  installed copy of every hook ran beside the checkout's copy. A regression in the checkout could
  pass because the installed copy enforced the same rule. It surfaced through the report-check loop
  below. The harness now passes `--setting-sources project,local`, and the fixture carries the
  `env` and `teammateMode` it needs from the user tier.
- **report-check could loop forever under a duplicated hook.** Each registration bumped the
  retry counter, and giving up cleared it, so the attempts cycled 1, 2, 1, 2 and every stop was
  still refused. An Explore agent that kept declining to end with its JSON report looped for 18
  stops on 2.1.286. Once it gives up, report-check now stays given up for that agent, for a day.
  The cost: a later SendMessage resume of that agent keeps its id, so a bad report then passes
  unchecked (the ledger still records `report_ok: false`).
- **Nested worktrees.** A lead session in a worktree nests its agents' worktrees inside it. The
  policy's cwd fallback took the first `/.claude/worktrees/`, which made the lead's whole worktree
  the agent's root; it now takes the last. The protected area (`main_root`) stays the outermost
  checkout, because it holds both the lead's worktree and the real main checkout.
- **Two test-suite bugs.** A project slug built by replacing only `/` and `.` failed about one run
  in five. And sandboxed from a checkout under `.claude/worktrees/`, the policy tests have nowhere
  clean to build their fake homes, so they now stop with one message that says so, instead of six
  wrong verdicts.

### Teams are off by default (A0)

A named spawn (an Agent call with a `name`) doesn't start a plain subagent. Claude Code starts an
in-process teammate instead: a member of an agent team, which reports through messages rather than
returning a result. Only a fork, or a spawn that passes `isolation` on the call, stays a subagent
("Team bypass" under the verified facts). So every named spawn silently became a teammate.

The 2026-09-30 re-evaluation found 57 teams on this machine, all implicit `session-<id>` teams, and
86 of the 89 teammates recorded in `~/.claude/teams/*/config.json` were general-purpose. Of 308
teammate messages, 293 went to the lead. Of the 15 peer-to-peer ones, 13 were report-delivery
churn between nested agents, so 2 were real coordination. Teammates also accounted for 10 of the
11 stalls in the eval (34 to 520 minutes). So a team bought almost nothing and cost the most.

`agent-spawn-guard` now denies a named spawn unless its name starts with the `team-` prefix
(`policy.toml` `[spawn] team_prefix`). A fork or an isolated spawn may still be named, and a
writer is still denied without `isolation`, prefix or not. Teams stay possible: the guard removes
the accidental path, not the deliberate one. The denial (intent `use_alternative`) says to drop the
name and SendMessage the returned id. It is recorded as a `named-spawn` policy row, so the monthly
audit can tell whether the guard is fighting real needs. SKILL §1b says when a team earns the
prefix.

### The canary and the due checks (A4, A5)

Stage 2's facts were verified on 2.1.285, and the machine was on 2.1.286 before anyone noticed.
Our enforcement leans on Claude Code internals that change without notice, and a change fails
silently:
- the policy hook fires only when hook input contains `"agent_id"`;
- a teammate's role sits in meta.json's `customAgentType`;
- a settings value of the wrong type is ignored.

Upgrades come almost daily here (2.1.284 to 2.1.286 landed in three days). So a check that waits
for someone to remember doesn't happen, and a full live run on every upgrade would cost about 15
sonnet sessions a day. The checks therefore split by cost (Hayden's call, 2026-09-30):

| Check | What it runs | When |
|---|---|---|
| Quick canary (`canary --quick`, about 20 s, no model calls) | the unit suites; `claude sandbox status` (the sandbox on, Bash auto-allow off); the strings our hooks read (`CANARY_STRINGS`), searched in the `claude` binary | by itself, in the background, on the first session of a new version |
| Audit (`audit`) | the enforcement audit above, over the window since the last one | by itself, once a day |
| Full canary (`canary`) | the quick tier, then the whole live harness (`run.py --runner claude`, all stages) | a reminder, when no green run is on record or the version has moved and the last green run is 7 or more days old, and after a failed run until one passes |
| Dated items (`skills/delegation/due.toml`) | whatever the item says | a reminder from its date on, until the item is removed |

**How it runs.** `hooks/delegation-due.sh` runs `delegation-ledger due --hook` at SessionStart
(`startup` and `resume`) in about 50 ms, and fails open:
- It reads `canary.json`, `audit.json` and `due.toml`.
- It starts the cheap checks as a detached job, so the session doesn't wait for them.
- It prints a line only when something needs Hayden: a failed check, a due full run, unseen audit
  warnings, or a dated item.
- The line goes out as `systemMessage`, which Claude Code shows to the user and the model never
  sees, so an upkeep note doesn't steer an unrelated session.
- A headless `claude -p` session (`CLAUDE_CODE_SESSION_ATTENDED=0`) still starts the cheap checks,
  but prints nothing and leaves the audit warnings unseen, since nobody reads its screen.

`delegation-ledger due` prints the same state on demand.

**It can't go quiet.** Anything that would stop the checks becomes a line of its own:
- a version `claude --version` doesn't print;
- a malformed `due.toml`;
- a crashing audit;
- a full run that failed. That one stays until a later run passes, even across upgrades.

State files of the wrong shape are read as empty, so they can't silence the rest. A live run
that reports fewer checks than the last green one isn't green either (`--accept-fewer` accepts a
deliberate cut).

**No audit gaps, up to a week.** The daily audit covers the time since the last one, capped at 168
hours, so only a machine unused for over a week leaves a stretch unaudited. A narrower manual run
doesn't move that mark. Warnings nobody has seen yet are kept until
a session start shows them. `audit` pairs each agent's start and stop across the window edge, so a
writer that ran over an audit boundary is still compared.

**Running the full tier.** It refuses to run inside the sandbox, because `claude -p` needs the
credentials the sandbox hides. The first real run (2.1.286, 2026-09-30) passed 52 of 52 checks in
about 5 minutes. A slow run can pass the Bash tool's 10-minute foreground limit, so the lead runs
it in the background.

**What a string check proves.** Not much, either way:
- A missing string means an upgrade renamed something we read, and that is worth stopping for.
- A present one proves little: `agent_id` could still exist in the binary and no longer reach
  PreToolUse. The live tier is what checks behavior, which is why it still runs weekly.

**Why dated items have their own file.** The policy hook fails closed on a malformed
`policy.toml`, and a typo in a reminder must never block a delegated agent.

### Liveness (A1)

Probe P2 showed that the stall timer doesn't abort an agent inside one long tool call. Before A1,
`open` called such an agent "silent N min". It couldn't name the tool or say since when, it misread
parallel calls, and its threshold was a hardcoded `--silent-min 30`.

**Liveness comes from the agent transcript, not from per-call hooks** (Hayden's call,
2026-09-30). A denied, failed or interrupted call writes a `tool_result` to the transcript but
fires no PostToolUse, so state kept by per-call hooks would get stuck on "in Bash". The
transcript has no such race:
- a `tool_use` id with no matching `tool_result` is a call still in flight;
- a new prompt (a resume, a teammate's next message) clears the open calls before it, so a call
  an abort left without a result doesn't read as in flight forever;
- every entry carries a timestamp, so the oldest open call says since when;
- a pending permission prompt shows as an open call too.

`open` reads the last 1 MiB of each agent's transcript. Its verdicts, in order:
1. the session is gone: `orphaned` (or `unknown` when no pid is visible, inside the sandbox; see
   "Watch (A3)");
2. a call is open: `in <Tool> N min` (`, +k more` for parallel calls), with a `⚠` past
   `tool_min`;
3. the turn ended but no stop row came: `finishing its turn` for the first minute, then
   `ended its turn but no stop row`, with a `⚠` (read the transcript for the report);
4. otherwise `running`, or `⚠ ask it for status` once no transcript entry has appeared for
   `silent_min`.

Codex rows get a `⚠` once `events.jsonl` has been quiet for `codex.silent_min`.

Notification and TeammateIdle hooks are left out: a pending prompt already shows as an open call,
`-p` can't produce a prompt to test with, and a teammate's stop on each message already marks it
idle. Their canary strings went too. A2 re-added PostToolUse, for the one hook its nudge needs.

**The index.** The ledger hook also keeps `$XDG_STATE_HOME/dotclaude/agents/<id>.json`. It is
rewritten at each start and stop (and once per activation by A2's nudge) under a lock, through a
temp file and a rename, so a reader never sees a torn file. It holds the agent's state, its
transcript path, `first_start`, and the current activation's start and count. A SendMessage
resume or a teammate's next message starts a new activation, with a fresh budget. `open` reads the
index for the activation and for the agent's kind (subagent or teammate). `watch` reads it too,
and so do both of A2's deadline hooks. A file untouched for 7 days is pruned at the next start.

**Why `liveness.toml` is its own file.** `load_policy` fails closed on a TOML syntax error, so a
typo in a value only `open` and `watch` read would block every delegated call. `liveness.toml` fails open
instead. A malformed file, or a value that isn't a positive number, falls back to the defaults in
`delegation-ledger`, and `open` and `watch` print the warning first, so it can't go quiet. This is the
`due.toml` reasoning. A2's deadlines went in `policy.toml` instead, because the policy hook
enforces them.

**`background_tasks` isn't used.** SubagentStop's `background_tasks` could have let `open` say
"stopped, waiting on N background tasks". A probe found the list session-wide, with no owner
field, so A1 neither records nor reads it (see the verified facts and the known gaps).

### Watch (A3)

`open` is for recovery: it lists everything unfinished, live or not, with the evidence behind each
verdict. `watch` is the view you glance at. It prints one line per live delegation, Claude and
Codex alike:

```
claude  a1b2  writer  dotclaude  in Bash 12 min  'add the watch view to delegation-ledger'
codex   20261001T101500-9f3a1c  gpt-5.6-sol  proj-x  running, last event 3 min ago
1 more unfinished but not live in the last 48h: delegation-ledger open
```

`watch --summary` prints the same count as a token for the tmux status bar: `<n>▶`, plus
` <w>⚠` when any line warns, or an empty line when nothing is live. `watch` prints once and
exits. A looping default would hold the lead's Bash call until the 10-minute limit; a human who
wants a loop runs `watch -n5 delegation-ledger watch`.

**Live only.** `watch` uses `open`'s rule for what is unfinished (a folded entry whose latest
event isn't a stop, within 48 hours), so the two views can't disagree. The index still supplies
the agent's kind and activation. Then `watch` keeps only what is live:
- an orphan or a dead Codex run only adds to a footer line that points at `open`;
- the token never counts one. Nothing can dismiss an orphan, so a token that stayed up for 48
  hours would teach you to ignore it;
- crash recovery stays `open --hours 24`.

**The grace.** A normal stop leaves a gap of up to about 3 seconds between the agent's `end_turn`
entry and its stop row (a worktree agent's SubagentStop hook runs `git status`). A 3-second poll
could catch that gap and flash a false `⚠`. So for its first minute (`STOP_GRACE_MIN`), both views
call such a turn `finishing its turn`, with no warning. After that, `ended its turn but no stop
row` gets a `⚠`.

**Known gap: a lost stop row can't be dismissed.** An agent in a live session whose stop row never
came keeps its line, and the token's `⚠`, for up to 48 hours. As of 2026-10-01, none of the 73
Claude agents in the live ledger has a start as its latest row, so a dismiss command waits until
this shows up.

**The tail read.** The ledger has no rotation, so `watch` reads only its last 1 MiB, which keeps a
3-second poll cheap. The cost: a start row more than about 2,900 rows back is missed by `watch`.
`open` reads the whole ledger, so it still has it.

**The sandbox finding.** Inside the Bash sandbox, no session pid is visible. Each sandboxed command
gets its own PID namespace: `CLAUDE_PID` names the session, yet `/proc/$CLAUDE_PID` is missing
inside the sandbox and present outside it. Before A3, a sandboxed `open` called every agent
`orphaned` and said nothing about why, and a sandboxed `watch` would have shown nothing live. Two
fixes:
- `delegation-ledger *` is in `sandbox.excludedCommands`, so a bare call runs outside the sandbox
  and is exact. The live settings are a copy, so a machine set up before A3 needs `./setup.sh`
  again (see "Installing on a machine that is already set up"). Delegated agents get `excluded-command` for it from the policy, and never need it.
- A self-check covers the calls that still run inside, such as a piped one. The caller's own
  Claude process is alive by definition, so when `CLAUDE_PID` is set but not alive, no pid check
  means anything. Both views then print a warning first and call each session `unknown` instead of
  gone, and `open` says `pid not visible in the sandbox` for a Codex row instead of `died`. With
  `CLAUDE_PID` unset (tmux, a plain terminal), the check passes.

A session file's `procStart` must now match the pid's start time too, so a pid the kernel reused
for another process no longer keeps a gone session alive.

**tmux.** `~/bin/tmux-claude-status` is machine-local and only renders the token; the repo owns
the `watch --summary` contract. The script is rate-limited to 3 seconds while the status line
redraws every 2, so a rate-limited run repeats the last token from a cache file. tmux replaces a
`#()` job's text with each run's output, an empty one included, so printing nothing there would
blank the token on every other redraw. An empty token from `watch --summary` itself just clears
the bar, which is what we want. The script also runs it with `CLAUDE_PID` unset. A `#()` job
inherits the tmux server's environment, so a server started from a Claude Bash call would carry
that session's `CLAUDE_PID` after it died, and that would trip the sandbox self-check.

### Deadline (A2)

A looping agent looks healthy. It keeps calling tools, so neither Claude Code's stall timer nor
A1's `⚠` fires, and nothing stops it. A2 gives each role a time budget per activation, in
`policy.toml` `[deadline]` (Hayden's numbers, 2026-10-01):

| Role | Nudge | Stop |
|---|---|---|
| Explore | 10 min | 20 min |
| researcher, reviewer | 20 min | 40 min |
| writer | 30 min | 60 min |
| `default`: general-purpose, Workflow agents, plugin types | 30 min | 60 min |

The 2026-09-29 eval measured subagents at p50 3.8 and p90 13.2 minutes. Explore's nudge sits
below that p90, since a read-only search that runs past 10 minutes is usually lost; the others sit
at 1.5 to 2.3 times it. A6 retunes the numbers against the ledger. `stop_min` defaults to twice
`nudge_min`, and fractions are allowed, which lets the live case run in seconds.

**The clock** is the liveness index's `activation_start`. Every SubagentStart begins an
activation: the spawn, a SendMessage resume, or a teammate's next message. So a resume gets a
fresh budget, and that is how the lead grants more time. The role comes from meta.json at call
time (`customAgentType` for a teammate), as for every other policy rule, not from the index.

**The nudge.** Past `nudge_min`, the agent's next successful call gets one PostToolUse
`additionalContext`: report now, finish or hand back `partial`, because at `stop_min` every tool
but the report path is denied. It lives in `delegation-ledger hook`, behind the same `agent_id`
prefilter as the policy hook. The filter matches the substring anywhere in the payload, so a
main-thread call whose input or output contains `"agent_id"` still starts Python, which returns at
once.
- It reads the index first and returns once `nudged` is set, so after the nudge it never takes the
  lock again.
- Otherwise it sets `nudged` under the index lock and checks again there, because parallel calls
  race. Only the call that set it prints the nudge.
- It appends a `nudge` row. `fold` skips those as it skips `policy` rows, so `open`, `watch` and
  `audit` never read a nudge as a lifecycle event. `tail` shows them.
- SubagentStart pops `nudged`, so each activation gets its own nudge.
- It names the nudge and the stop apart ("past the 30 min nudge ... at the 60 min stop"). The
  first wording, "66.1 min of this activation's 30 min budget", read as the stop itself, and an
  agent quit at the nudge.
- It fails open throughout. A broken `[deadline]` means no nudge, while the policy hook fails
  closed on the same file.

**The stop.** Past `stop_min`, `subagent-policy` denies every tool except `[deadline] allow`, the
report path, with stop_and_explain, so the agent can still hand back `partial`. It runs before
every other rule, and it covers every tool, not only the policed ones (Hayden's call, 2026-10-01).
Otherwise WebFetch, WebSearch and the Task tools stay open, and an agent looping on the web never
stops. The report path is three tools:
- SubagentHandback, how a subagent reports;
- SendMessage, how a teammate reports and how the lead resumes an agent;
- ToolSearch, because SendMessage is deferred for a teammate. The teammate check found a stopped
  teammate whose ToolSearch was denied, so it could only report by calling SendMessage without
  its schema. ToolSearch only loads schemas, so a tool it loads is still denied (Hayden's call,
  2026-10-01).

The deny brings its own footer instead of stop_and_explain's "rewrite the command", so it reads as
one message:

```
[subagent-policy] deadline (stop_and_explain): this activation has run 61 min, past the 60 min
stop for writer. Only SubagentHandback, SendMessage and ToolSearch are allowed now. Hand back a
`partial` report naming what is done and what is left. If the lead resumes you, the budget starts
over and every tool works again.
```

The check fails open on an unreadable index (no index, no clock) and never becomes a
`policy-error`. A malformed `[deadline]` table fails closed, like the rest of `policy.toml`: every
policed tool is denied, whatever the clock says. The tools it doesn't police (the handback,
SendMessage, WebFetch, WebSearch, ToolSearch) still pass on a broken file, as they always have, so a
policy bug can't swallow a report.

**Why `policy.toml`.** The policy hook enforces the stop, so a broken value must fail closed.
`liveness.toml` is a file of its own for the opposite reason: only `open` and `watch` read it, so
it fails open.

**The state dir is protected.** `{state_dir}` joined `[protect] write_denied`. It expands to
`$XDG_STATE_HOME/dotclaude` (default `~/.local/state/dotclaude`), wherever the ledger actually
writes. The OS sandbox covers only Bash, so a general-purpose agent's Write tool could otherwise
rewrite its own index and reset its clock.

**Checks run between calls,** so a long call that is already running finishes, and the stop lands
on the next one. The main thread is exempt. Codex keeps `codex-delegate --timeout`.

**Known gaps:**
- **The nudge rides only a successful call.** PostToolUse doesn't fire for a denied, failed or
  interrupted call, so an agent whose calls all fail past `nudge_min` meets the stop with no
  warning.
- **An agent with no index has no deadline.** Claude Code's helper agents (empty `agent_type`)
  never get one, and neither does an agent whose SubagentStart hook failed.
- **Workflow agents share `default`.** Their hook `agent_type` is `workflow-subagent` in every
  workflow, so one budget fits all of them.
- **A teammate of a built-in type has no role.** Its meta.json carries no `customAgentType`, and
  its `agentType` is its name, so its budget is `default` and the messages name it. Harmless
  today, since general-purpose's budget is `default`. Our own roles do carry `customAgentType`.

## Verified facts the design rests on

First checked against Claude Code 2.1.285 and Codex CLI 0.154 on 2026-09-30, then re-run on each
version since with the full live harness. A fact added later names its own version. "Probe" means
a live `claude -p` run with a real sandbox. Where the docs and the binary disagree, the binary
wins.

- **Grep and Glob:** on Linux and WSL they are absent by default. They come back for a subagent that
  lists them in `tools` and leaves out Bash
  ([tools-reference](https://code.claude.com/docs/en/tools-reference), "Glob tool behavior").
- **Explore override:** "A user or project subagent named `Explore` overrides the built-in and keeps
  its own `model` field" ([sub-agents](https://code.claude.com/docs/en/sub-agents)). The live harness
  shows this: under a haiku lead, the Explore transcript runs on sonnet.
- **Built-in Explore** (read from the 2.1.285 binary): it denies only the edit tools, keeps Bash, and
  has `omitClaudeMd: true` and `model: inherit`. Its prompt forbids writes in prose.
- **Team bypass:** "a subagent that Claude spawns from the main conversation with a `name` launches as
  a teammate instead, unless the call is a fork or passes `isolation` on the call itself"
  ([sub-agents](https://code.claude.com/docs/en/sub-agents)).
- **Teammate mode:**
  - the binary's default is `in-process` (the docs say so too);
  - all 89 recorded teammates (rechecked 2026-09-30) in `~/.claude/teams/*/config.json` ran with `backendType: in-process`;
  - teammate `meta.json` files carry `teamName`.
- **Worktree base:** `isolation: worktree` branches from the default branch unless
  `worktree.baseRef` is `"head"` ([worktrees](https://code.claude.com/docs/en/worktrees)).
- **Hook input** (probe):
  - `agent_id` and `agent_type` appear on a subagent's PreToolUse, SubagentStart and SubagentStop,
    and never on the main thread;
  - a worktree subagent's `cwd` is its worktree;
  - `transcript_path` is the parent session's, and
    `<it minus .jsonl>/subagents/agent-<id>.meta.json` has `worktreePath`;
  - Bash `tool_input` carries `dangerouslyDisableSandbox` when it is set;
  - SubagentStop carries `stop_hook_active`, `agent_transcript_path`, `background_tasks` and
    `session_crons`.
- **Hook precedence and blocking:**
  - "precedence is `deny` > `defer` > `ask` > `allow`", and exit 2 routes like deny;
  - a PreToolUse deny holds in bypassPermissions;
  - a hook timeout does not block;
  - the default command-hook timeout is 600 s ([hooks](https://code.claude.com/docs/en/hooks)).
- **Handbacks** (the binary):
  - `SubagentHandback` takes `{message}`;
  - it exists only in auto mode;
  - a subagent that ends without a delivered handback gets up to 3 nudges, then its report is lost.
    That is why the report check stops at 2 rejections.
- **Other hook events:**
  - SubagentStart fires "each time an in-process agent team teammate handles a new message", so the
    ledger folds rows by `agent_id`;
  - Claude Code's own helper agents fire SubagentStop with an empty `agent_type` and no transcript;
  - in `-p` mode a folder is treated as trusted, so project hooks run.
- **Silent failure modes:** Claude Code ignores an agent frontmatter field it doesn't recognize, and
  a settings value of the wrong type is ignored too. That is why `test_agents.py` and
  `test_settings.py` pin names and types.
- **Sandbox settings** (the binary's schema):
  - `allowUnsandboxedCommands` is a **bool**, default true. The settings reference shows a string
    enum;
  - `autoAllowBashIfSandboxed` defaults to **true**. Enabling the sandbox with the default would
    stop Hayden's Bash prompts, so the baseline sets it to false;
  - `failIfUnavailable` exists. Without it, a sandbox that fails to start falls back to
    unsandboxed silently (#84563);
  - `excludedCommands` is honored only from the user, managed and `--settings` tiers;
  - `claude sandbox status` (a hidden subcommand) prints the posture as JSON.
- **Sandbox behavior** (probe):
  - Bash writes outside cwd fail with "read-only file system", including `/tmp` outside
    `/tmp/claude-<uid>`;
  - a `denyRead` directory reads as empty, and a `denyRead` file as permission denied;
  - `~` expands in `denyRead` and `allowWrite`, and a missing path is skipped harmlessly;
  - an unlisted domain is refused and reported as `<sandbox_violations>` in the tool result.
- **`excludedCommands` matching** (probe):
  - `"cp *"` matched `cp a b` (the command left the sandbox and hit the permission gate);
  - a bare `"touch"` did not match `touch x`;
  - a compound command stays sandboxed even when one part matches;
  - so the main thread's `cd x && git push` fails on the credential, and then retries through the
    escape.
- **Seccomp:**
  - the filter is embedded in the native binary; the npm package is not needed;
  - in the probe, `socket(AF_UNIX)` failed with EPERM and `cmd.exe` failed to launch;
  - unix sockets are all-or-nothing on Linux (`allowUnixSockets` is ignored there), so tmux,
    `systemd-run --user` and Windows binaries run through `excludedCommands`.
- **Protected paths:** `.claude/settings*`, skills, agents, hooks, `.mcp.json`, `.git/hooks` and
  `.git/config` stay read-only for sandboxed Bash, even inside a writable root
  ([sandboxing](https://code.claude.com/docs/en/sandboxing)).
- **The Bash tool's shell:**
  - it runs zsh with the shell snapshot's aliases (237 here, including oh-my-zsh's `gp`, `grhh`
    and `gstc`);
  - its PATH matches the hook's;
  - Claude Code defines `grep` (its bundled ugrep, which has `--filter`), `find` and `rg` as
    functions.
- **Teammate reporting:** teammates report to the lead through `teammate-message` and
  `idle_notification` events, not task notifications.
- **Stall timeout:** `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS` (default 10 minutes) aborts a subagent that
  makes no progress ([env-vars](https://code.claude.com/docs/en/env-vars)). Probe on 2.1.286
  (`run.py` case `stall`): a background agent inside one 100-second tool call finished under a
  45-second timer, so a single long call isn't aborted. There is no negative control, so this
  doesn't show the timer fires at all in that setup. A silent agent can therefore sit in one call
  far past the timer; `open` shows it as `in <Tool> N min` (A1).
- **Transcript entries** (2.1.286): a `tool_use` entry is written before its tool runs, and every
  user and assistant entry carries a `timestamp` with milliseconds. A1's liveness rests on the
  first; the `stall` case checks it live, since a poll of `open` and of `watch` during its
  100-second call must show `in Bash`.
- **SubagentStop `background_tasks` is session-wide** (probe on 2.1.286, 2026-10-01). The lead
  backgrounded `sleep 20`, then spawned a background agent that backgrounded `sleep 30` and ended
  its turn. The agent's list held three entries: the agent itself (`type: "subagent"`, with
  `agent_type`), the lead's shell task and the agent's own (`type: "shell"`, with `command`). No
  field names an owner.
- **A subagent isn't woken by its background task** (same probe): no second SubagentStart fired
  when the agent's task finished. A subagent that backgrounds a command and ends its turn never
  sees the result.
- **`CLAUDE_PID` and the sandbox's PID namespace** (2.1.286, 2026-10-01): Claude Code sets
  `CLAUDE_PID` in the lead's Bash env, inside the sandbox and outside it, and it names the
  session's Claude process. Each sandboxed command gets its own PID namespace, so
  `/proc/$CLAUDE_PID` exists outside the sandbox and is missing inside it, where no session's pid
  is visible. `SANDBOX_RUNTIME=1` is set only inside; A3 doesn't rely on it.
- **`procStart`** (same day): a session file `~/.claude/sessions/<pid>.json` carries `procStart`,
  which equals field 22 (starttime) of `/proc/<pid>/stat`. The command name in that file may hold
  spaces, so the fields are split after the last `") "`.
- **tmux `#()` jobs** (tmux 3.7c, 2026-10-01): tmux replaces a job's text with each run's output,
  an empty one included.
- **Workflow agents** (probe on 2.1.286, case `workflow`): their PreToolUse, PostToolUse and
  SubagentStart carry `agent_id`, with `agent_type: "workflow-subagent"`, and the policy denied
  one's `git push`. Under `-p` the Workflow tool first asks for review ("Review dynamic workflow
  before running"), so the harness pre-allows it.
- **Teammate identity** (live session, 2.1.286): a teammate's hook `agent_type` is its name. Its
  meta.json has `agentType` (the name), `name`, `customAgentType` (the role it was spawned as),
  `taskKind: "in_process_teammate"` and `teamName`. The agent definition still binds (model and
  tools). `agent_id` looks like `ateam-probe-<hex>`.
- **SessionStart output** (interactive probe, 2.1.286): a hook's `systemMessage` shows on screen as
  `SessionStart:startup says: <text>`, and its `additionalContext` doesn't show. A child the hook
  starts in a new session (`start_new_session`) outlives the hook. SessionStart fires for
  `claude -p` too (`source: "startup"`), and there the hook's environment has
  `CLAUDE_CODE_ENTRYPOINT=sdk-cli` and `CLAUDE_CODE_SESSION_ATTENDED=0`, against `cli` and `1` in
  an interactive session.
- **meta.json timing:** a plain subagent's meta.json doesn't exist yet at SubagentStart; it does by
  SubagentStop. A named plain subagent's meta.json carries `name`.
- **A doubled SubagentStop:** in auto mode, an agent that ends with plain text stops, then Claude
  Code injects `[handback-send-enforce]` and it stops again after `SubagentHandback`. Each stop
  fires the hook.
- **PostToolUse and resumes** (A2's Step 0 probe on 2.1.287, 2026-10-01; settings, prompt, raw
  hook input and output in `~/scratch/delegation-writeup/evidence/a2-step0/`):
  - a subagent's PostToolUse input carries `agent_id` and `agent_type`, plus `tool_name`,
    `tool_use_id`, `duration_ms`, `prompt_id` and `transcript_path`. The main thread's has
    neither id field;
  - a PostToolUse hook's
    `{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"..."}}` lands in
    the agent transcript as an `attachment` entry with `attachment.type ==
    "hook_additional_context"`, next to a `hook_success` entry. It never appears as an
    attachment in the lead's transcript;
  - a SendMessage resume of a plain subagent fires a second SubagentStart with the same
    `agent_id`, then a second SubagentStop, so a resume gets a fresh deadline through the
    ledger's existing start. `-p` can resume: SendMessage loads through ToolSearch;
  - told nothing about order, the agent ran its Bash and Read calls in parallel. The `deadline`
    case in the live harness asks for one call per turn.
- **The deadline on a teammate** (a manual check on 2.1.287, 2026-10-01, since `-p` can't make a
  teammate). A `team-` general-purpose teammate in an interactive session, under the installed
  hooks, had its `activation_start` backdated 65 min during a 60-second call:
  - the call finished, and its PostToolUse brought the nudge ("66.1 min of this activation's 30
    min budget"), so a teammate's PostToolUse carries `agent_id` too;
  - its next two calls were denied with `deadline (stop_and_explain)`;
  - SendMessage is a deferred tool for a teammate. Its ToolSearch to load the schema was denied
    too, and it reported only by calling SendMessage without the schema. ToolSearch is in
    `[deadline] allow` since;
  - a general-purpose teammate's meta.json has `agentType` set to its name and no
    `customAgentType`, so its budget falls to `default`.
- **Codex sub-agents:**
  - a `spawn_agent` without a model inherits the parent's model (tested);
  - `agents.default_subagent_model` exists, and `codex-delegate` passes it with `-c`;
  - an explicit model argument still overrides both;
  - a child can't get its own sandbox;
  - a child rollout's first `session_meta` carries `payload.parent_thread_id`;
  - `--json` emits no heartbeat event;
  - `--output-schema` applies per turn, so resume must pass it again.

## Adopt, copy or build (survey, 2026-09-29)

No existing setup was worth building on, so we built a thin layer on native controls and took
patterns from these:
- **Per-agent scope:** nothing enforces it. agent-pd only detects.
- **Agent collections** (wshobson, VoltAgent) persuade only, and their reviewers carry Bash or Write.
- **Orchestrators:** ruflo/claude-flow is hype, claude-squad is AGPL, and vibe-kanban and Conductor
  follow a different architecture.
- **codex-plugin-cc** is kept for interactive `/codex:*` use, not for scripted delegation.

| Source | License | What we took | Where |
|---|---|---|---|
| kenryu42/cc-safety-net | MIT | The destructive-command rule table, the five block intents and their footers, the wrapper-peel and recursion caps, fail closed on any exception | `policy.toml`, `subagent-policy`, spawn guard, `BRIEF.md` |
| Parable (ldayton/Parable, as pinned by ldayton/Dippy) | MIT | The bash parser, **vendored verbatim** (`scripts/vendor/parable.py`, pinned by sha256), with Dippy's walk-every-node approach reimplemented | `subagent-policy` |
| oscarthroedsson/breadcrumb | MIT | The SubagentStop rejection counter, keyed on session and agent, with a cap of 2 | `report-check` |
| stefanprodan/cctop | Apache-2.0 | The session rule: `~/.claude/sessions/<pid>.json` plus `/proc` (A1's transcript scan replaced its last-entry rule) | `delegation-ledger open` |
| openai/codex-plugin-cc `job-control.mjs` | Apache-2.0 | Phase inference from the event log | `codex-delegate status` |
| obra/external-subagents | none (idea only) | A pending row before launch; idle minutes | `codex-delegate` |

Apart from Parable, everything is reimplemented. dcg is out: its license rider excludes anyone
acting for Anthropic or OpenAI.

## Next

**Stage 3 (watch)** is planned in `~/.claude/plans/lets-move-on-to-refactored-pascal.md`, which
replaced the bullets that stood here. Its order: Step 0 probes, then A0 (named spawns off),
A4 and A5 (due nudges, a one-command canary), A1 (per-agent liveness state), A3 (one watch view),
A2 (deadline nudge, then hard stop), A6 (monthly audit). "Stage 3" above says which are done. A6
is next, and it retunes A2's budgets against the ledger.

## Tests

- **Unit:** `python3 -m unittest discover -s tests/delegation -t tests/delegation`. They make no model
  calls. The policy tests run against this repo's baseline `sandbox` block, and the codex-delegate
  tests use a fake `codex` on `PATH`. Sandboxed from a checkout under `.claude/worktrees/`, the
  policy tests refuse to run (their fake paths would read as inside that worktree); run them with
  the sandbox off there.
- **Live:** `python3 tests/delegation/run.py --runner claude` runs short `claude -p` sessions (sonnet;
  the reader case uses a haiku lead) in a disposable fixture.
  - The fixture's project settings wire the hooks by absolute path and turn the sandbox on, and
    every session runs with `--setting-sources project,local`, so only this checkout's hooks run,
    before anything is installed.
  - Pick cases with `--cases`, or a stage with `--stage`.
  - `--runner codex` runs one short Terra run.
- **Canary:** `delegation-ledger canary` runs the unit suites, the posture and string checks, then
  the live harness, and records the result for the due checks. After an upgrade, or a change to a
  role, a hook or `codex-delegate`, run it outside the sandbox and in the background. `--quick`
  runs only the cheap tier. It runs anywhere, but it records its result only outside the sandbox,
  where the state dir is writable.
- **Results on 2026-09-30 (Claude Code 2.1.286):**
  - unit: 213 tests;
  - canary: the first full run, before PR #46 merged, went green: the quick tier, then 52/52 live
    checks;
  - claude: 52 checks over all three stages. The last full run passed 51. The miss was the old
    `report (auto)` check, which asserted that the model complies: it kept the brief's "no JSON"
    rule all three times, and the cap let it through as designed. The check now asserts the
    contract instead (valid, or recorded invalid after exactly two send-backs), and it passed live.
    An earlier full run lost `deps` to a chained command (see the known gaps); it passes with one
    call per step. The computed-path escape reached the main checkout, as the known gap predicts,
    and `audit` flagged it;
  - the Stage 2 baseline run with user settings still loaded went 36/37. That failure was the
    report-check loop, and it led to the `--setting-sources` fix;
  - codex: 7/7 (on 2.1.285, not rerun).
- **Results on 2026-10-01 (A1, 2.1.286):**
  - unit: 233 tests;
  - claude: the `stall` case passed 4 of 4, including its two new liveness checks, so a full run
    now has 54 checks.
- **Results on 2026-10-01 (A3, 2.1.286):**
  - unit: 250 tests;
  - claude: the `stall` case passed 6 of 6, including its two new checks (`watch` showed the
    agent in Bash, `watch --summary` counted it as `1▶`), so a full run has 56 checks;
  - after the merge and `setup.sh`, the full canary passed 56 of 56. A manual probe in one
    120-second call showed `in Bash` in a bare `watch`, while a piped `watch` gave the sandbox
    warning. `watch --summary` took 41 ms (median of 10), and the tmux token showed `1▶`, then
    cleared when the probe stopped.
- **Results on 2026-10-01 (A2, 2.1.287):**
  - before the build, the quick canary went green on 2.1.287 (250 + 19 unit tests, sandbox
    posture, all 17 strings);
  - unit: 270 tests, plus 19 in `tests/setup`;
  - claude: the new `deadline` case passed 9 of 9, so a full run has 65 checks. The nudge landed
    once, in the agent's transcript only. The second Read was denied at 0.6 min against the 0.4 min
    stop, and the agent handed back `partial`. After the SendMessage resume, a second activation
    (`activations` 2, `nudged` cleared) let its Read through.
  - after the merge and `setup.sh`, the full canary went 64 of 65 in 6 min 11 s. The miss: after the
    resume, the agent wouldn't call Read. It took the resume as a retry of its denied step, which
    its brief forbade, and the denial's "allowed now" as still in force. The mechanism held (a
    second activation started), but a real resumed agent has the same blind spot. So the denial
    now says a resume restarts the budget, and the case's resume message says it isn't a retry.
    The case then passed 9 of 9 twice.
  - after that fix merged (PR #52), the full canary passed 65 of 65 in 6 min 0 s, so 2.1.287 is
    green;
  - the manual teammate check passed: nudge and stop both reached the teammate (see "Verified
    facts"). It found ToolSearch missing from the stop's allow list, now added;
  - the next `deadline` run went 6 of 9: the agent obeyed the nudge, handed back after step 1, and
    never reached the stop. The nudge now names the nudge and the stop apart, and the case tells
    the agent the reminder is expected and to carry on.

## Installing on a machine that is already set up

`setup.sh` links everything below. It also **resets** `~/.claude/settings.json` to this repo's
baseline plus `settings.machine.json`, keeping only the top-level keys the baseline doesn't set (see
the README). So a hook that is only in the live file (for example `tmux-state.sh`) is lost unless it
is in the overlay. On a machine without that overlay, do it by hand, **in this order**. The spawn guard and the policy
hook fail closed, so wiring a hook before its script is reachable blocks every delegated call.

1. **Links.**
   - `skills/delegation` → `~/.claude/skills/delegation` (the hook shims call its scripts).
   - `agents/*.md` → `~/.claude/agents/`.
   - `hooks/{agent-spawn-guard,delegation-ledger,delegation-due,subagent-policy,report-check}.sh`
     → `~/.claude/hooks/`.
   - `codex-delegate`, `delegation-ledger` and `gh-public` → `~/.local/bin/`.
2. **Check the scripts before wiring them.**
   - The spawn guard, with
     `echo '{"tool_name":"Agent","tool_input":{"subagent_type":"writer"}}' | XDG_STATE_HOME=$(mktemp -d) bash ~/.claude/hooks/agent-spawn-guard.sh`,
     must print a deny, and so must `{"tool_name":"Agent","tool_input":{"name":"x"}}`. The
     throwaway `XDG_STATE_HOME` keeps the denial rows out of the real ledger.
   - The policy, with `{"agent_id":"x","tool_name":"Bash","tool_input":{"command":"git push"},"cwd":"/tmp"}`
     through `bash ~/.claude/hooks/subagent-policy.sh`, must print a deny. It denies Bash until the
     sandbox block is in, which is expected.
3. **The hook entries.** Add the PreToolUse entries (`*` for the policy, `Agent|Task` for the guard,
   `SubagentHandback` for the report check), the PostToolUse `*` entry (the deadline nudge, A2) and
   the SubagentStart and SubagentStop entries to the live `~/.claude/settings.json`, copied from
   the baseline. The nudge fails open, so its place in the order doesn't matter. Then spawn an
   `Explore` agent and check:
   - its transcript runs on sonnet;
   - the ledger has start and stop rows (`delegation-ledger tail`);
   - `delegation-ledger audit` says the policy hook saw it.
4. **The sandbox.** Add the `sandbox` block and `teammateMode`, then **restart Claude Code**: the
   dependency check runs only at startup. In the new session:
   - `claude sandbox status` shows enabled;
   - a Bash write outside cwd fails;
   - `cat ~/.config/gh/hosts.yml` fails;
   - `git fetch` and `gh pr list` still work, through the exclusion;
   - a bare `delegation-ledger watch` prints no "no pid is visible" warning, so the
     `delegation-ledger *` exclusion (A3) is in;
   - the prompts are unchanged.
5. **The due checks.** Add the SessionStart entry (`delegation-due.sh`), then run
   `delegation-ledger canary` outside the sandbox, in the background. When it is green, a new session
   prints nothing unless something is due, and `delegation-ledger due` shows the state. The hook fails
   open, so its order doesn't matter.

**If Claude Code won't start** because the sandbox can't (a missing bwrap after an upgrade, say), set
`"enabled": false` under `sandbox` in `~/.claude/settings.json` with an editor. That also takes
delegated agents' Bash away, until the sandbox is back.

Observed on the 2026-09-30 install: skill links and settings hooks took effect in the running session
at once. Agent definitions reloaded a little later: the first `Explore` spawn after linking still got
the built-in. So check the override with a fresh spawn, or in a new session.
