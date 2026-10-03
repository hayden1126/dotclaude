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
- **general-purpose:** 118 general-purpose subagents ran. 47 edited files, 43 to 50 more
  ran mutating shell commands (depending on what counts as mutating), and fewer than a quarter only
  read. All 5 that misbehaved had read-only briefs, and 4 of them were reviews or audits.
  Counting teammates by the role they were spawned as, 11 of the 12 drift cases were
  general-purpose agents. The twelfth was the built-in Explore, which also keeps Bash.
  (Recomputed from the eval's extract on 2026-10-01.)

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
   - The ledger records every start, stop, denial and deadline nudge, and the exclusions that
     keep probes out of `audit --monthly`.
   - `audit` flags a hook that stopped seeing agents, and a writer run that coincided with a
     main-checkout change.
   - `sandbox-denials` lists what the sandbox refused.
   - The canary re-verifies all of this on a new Claude Code version, and a SessionStart check
     runs the cheap checks itself and reminds Hayden of the rest ("Stage 3", A4 and A5).
5. **The watch guard** covers the main thread's liveness. A Stop hook blocks a turn's end once
   when a long wait has lapsed or a background command was killed at its time limit ("Long
   waits (the watch guard)").

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
| Ledger | `hooks/delegation-ledger.sh`, `skills/delegation/scripts/delegation-ledger`, `skills/delegation/liveness.toml` | Observes: start and stop rows (`agent_type` is the resolved role; a teammate adds `name` and `teammate`), `report_ok`, denial rows, the main-checkout hash for a worktree agent; the per-agent liveness index (`agents/<id>.json`); `open` (the tool in flight and since when, thresholds in `liveness.toml`); `watch` (one line per live delegation, and a token like `2▶ 1⚠` for the tmux bar); `audit` (`--monthly` adds a month of usage for retuning, and `exclude` keeps probes out of it); `sandbox-denials`. Persuades: the deadline nudge, one PostToolUse `additionalContext` per activation past the role's `nudge_min`, and a `nudge` row. Fails open |
| Canary and due checks | `hooks/delegation-due.sh`, `skills/delegation/scripts/delegation_checks.py`, `skills/delegation/due.toml` | Observes: `delegation-ledger canary` re-verifies enforcement on this Claude Code version; `due` runs the cheap checks at session start and shows Hayden what needs him. Fails open |
| Public GitHub client | `skills/delegation/scripts/gh-public` | GET-only access to api.github.com for delegated agents, optionally with a public-read token |
| Brief and report | `skills/delegation/BRIEF.md`, `report.schema.json` | Persuades (the brief); checks (the schema) |
| Codex wrapper | `skills/delegation/scripts/codex-delegate` | Enforces: model gate, sandbox, memory cap (via systemd-run when available, otherwise a warning), timeout, schema, and a recursive model audit. Records its own watch, with itself as the waiter, and exits 75 at `--max-wait`, before the Bash cap |
| Waiter | `delegation-ledger wait` | Enforces liveness: records a watch, polls it with a heartbeat, and exits before the Bash cap with the exact re-arm line. Refuses to run sandboxed |
| Watch guard | `hooks/watch-guard.sh`, `skills/delegation/scripts/watch-guard`, a `Stop` entry in `settings.json` (timeout 5) | Enforces liveness on the main thread: blocks a stop once per lapsed watch and once per command killed at its time limit. Fails open |
| Re-arm allow rule | `settings.json` `permissions.allow`: `Bash(delegation-ledger wait *)` | A re-arm never stops at a permission prompt |
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
  appears in any settings file. One such wrapper lives in a separate project-registry repo: each
  MCP server's launch command runs through it, and it exports only that server's variables. An
  `envVars` deny list is the fallback; it names each variable, so it belongs in the private live
  settings, not this baseline.
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
- **The watch guard covers the main thread only.** It is a Stop hook, and it skips a payload
  with `agent_id`. Subagents and teammates are out of its scope: `BRIEF.md` forbids ending a turn
  with a background command running, and the deadlines cap an activation well under 2 hours.
- **A lead that ends its turn with nothing in the background isn't caught.** With no watch and no
  killed command there is nothing to block on. The guard catches a lapsed or killed wait, not a
  wait that was never started.
- **The guard's first run in a session looks back 10 minutes.** It sets the kill record's
  `since` 10 minutes back and starts its first scan 256 KB from the transcript's end, so an older
  kill never blocks.
- **A sandboxed `codex-delegate` records no watch** and ignores `--max-wait`: its pids mean
  nothing outside its PID namespace, and Codex could die with that namespace. It says so on
  stderr. With no launch line, a kill of it can't fold into a watch either.
- **One stop can skip an item.** A watch whose write fails mid-commit is logged and skipped for
  that stop, and comes up at the next. A lock still busy after the gather budget skips the whole
  stop. An item past the 3 s gather budget waits for the next stop.
- **A met condition is judged on a log's last 1 MB.** A `--done` line further back reads as unmet
  to the guard, so the watch lapses instead of ending. The re-armed waiter reads the whole log.
- **The duplicate refusal is per run, across sessions.** A second `wait --codex` on a run that
  any session watches is refused. While that watch's waiter is alive and its session is live,
  the refusal says the waiter will notify its session. Otherwise it names `wait --resume <id>`,
  which moves the watch to the caller's session.
- **An acknowledged lapse goes quiet.** After one block and one warning, a lapsed watch stays
  open and says nothing more in that session until it ends: it blocks once more when its
  condition is met, or when its codex run gets a stop row or turns out never to have started.
  The session-start nudge lists it once no running session holds it: its Claude Code process
  has ended, and nobody continued its session.
- **A live waiter can read as lapsed.** A waiter whose heartbeat is older than two polls plus a
  second (a suspended VM, say) counts as dead: the guard blocks on it, and a `--resume` can take
  the watch over. The old waiter steps aside at its next beat.
- **A killed waiter's fold falls back to a heuristic.** It folds by the launch line in the
  command's output file. With no launch line there (the waiter was killed before it printed
  one), it needs the watch its `--resume` names, or one watch created within 120 s after the
  launch, told apart by `--pid`, `--file` or `--log`. When that names no single watch, the stop
  says the kill and the lapse as two items.
- **Adoption after `/clear` needs the Claude process.** A waiter and the guard each find their
  Claude process by walking up their parents, 6 levels at most, to the nearest one whose
  `~/.claude/sessions/<pid>.json` names its pid and procStart (`claude_ancestor`, which returns
  that process and the file's `sessionId`). `claude_identity` decides from there, and a
  waiter's session comes from the same walk. `CLAUDE_PID` and `CLAUDE_CODE_SESSION_ID` are inherited, so
  on their own they can name another process's session: a nested `claude -p` started from the
  lead's Bash may carry the lead's, and a tmux server started from a Claude Bash call carries
  ones that go stale. So:
  - when `CLAUDE_PID` is the process the walk found and `CLAUDE_CODE_SESSION_ID` is set, that
    process set both vars for this Bash call, and the env's id is the session. The env follows a
    session change (see the verified facts), and nothing verified says the sessions file is
    rewritten before the first Bash call after a `/clear`. A nested `claude -p` sets its own
    vars, so this holds there too;
  - otherwise, when the walk finds a process, its sessions file's `sessionId` is the session
    (`unknown` without one). The file decides whenever the env can't: the walked process isn't
    `CLAUDE_PID`, so the env may be another process's, or the env names no session;
  - when the walk finds nothing, the env counts only when `CLAUDE_PID` is an ancestor of the
    command, at any level: then it is the process, and `CLAUDE_CODE_SESSION_ID` the session.

  A watch made outside Claude Code records no process and the session `unknown`, and a guard
  that finds no process adopts nothing. Adoption also rests on the sessions file naming the new
  session id after a `/clear` (see the verified facts). The file still decides which sessions
  are live (`live_sessions`), so it decides when the old id stops being live and its watch can
  be adopted, and it names the session of a walked process that isn't `CLAUDE_PID`. Were the
  rewrite to stop, the old session would read as live and nothing would be adopted: safe, but
  the old watch would go unguarded. A new watch would still get the new id, from the env.
- **A crash, then `claude --continue`, rests on the session id.** The guard adopts a crashed
  process's watch only in the session that has its id, so this assumes `--continue` keeps the
  session id. That isn't verified here; the manual re-arm check in `due.toml` asks for it. With a
  new id, nothing blocks, but the session-start line shows the watch instead: an unresolved one
  as nobody's, and one whose waiter ended meanwhile as an end nobody heard, once.
- **The re-arm across turns isn't in the live harness.** `claude -p` kills background shells
  about 5 s after its final result, so no waiter outlives a `-p` turn. A dated item in `due.toml`
  asks for the check by hand in an interactive session.
- **The private notes repo.** There is deliberately no read deny on it. A session-wide deny would
  break the project registry, which routes notes into it, and the sessions that run inside the
  notes repo itself. Bash writes to it from other sessions are already outside the write roots.

## Stage 3

Stage 3 makes the setup check itself instead of relying on someone remembering. It runs in steps,
Step 0 and then A0 to A6, planned in `~/.claude/plans/lets-move-on-to-refactored-pascal.md`. All of it is
done: Step 0, A0, A4, A5, A1, A3, A2 and A6.

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
| Quick canary (`canary --quick`, about 20 s, no model calls) | the unit suites; `claude sandbox status` (the sandbox on, Bash auto-allow off); the strings our hooks read (`CANARY_STRINGS`), searched in the `claude` binary; the installed `watch-guard.sh`, run with a no-op main-thread payload and a throwaway state dir, which must exit 0 and log nothing (proving the link and the import) | by itself, in the background, on the first session of a new version |
| Audit (`audit`) | the enforcement audit above, over the window since the last one | by itself, once a day |
| Full canary (`canary`) | the quick tier, then the whole live harness (`run.py --runner claude`, all stages) | a reminder, when no green run is on record or the version has moved and the last green run is 7 or more days old, and after a failed run until one passes |
| Monthly audit (`audit --monthly`) | the audit over 30 days, plus the usage sections (A6) | a reminder, once the ledger and the last monthly run are both a month old |
| Dated items (`skills/delegation/due.toml`) | whatever the item says | a reminder from its date on, until the item is removed |

**How it runs.** `hooks/delegation-due.sh` runs `delegation-ledger due --hook` at SessionStart
(`startup` and `resume`) in about 50 ms, and fails open:
- It reads `canary.json`, `audit.json`, `due.toml` and the ledger's first row.
- It starts the cheap checks as a detached job, so the session doesn't wait for them.
- It prints a line only when something needs Hayden: a failed check, a due full run, unseen audit
  warnings, a due monthly audit, or a dated item.
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
- A self-check (`pids_visible`) covers the calls that still run inside, such as a piped one.
  `SANDBOX_RUNTIME=1`, set only inside, fails it. So does a `CLAUDE_PID` that is set but not
  alive, since the caller's own Claude process is alive by definition, unless the parent walk
  (`claude_ancestor`, in the known gaps) finds a live Claude process anyway: then `CLAUDE_PID`
  was only stale, inherited from a process that has ended. When it fails, no pid check means
  anything, so both views print a warning first and call each session `unknown` instead of
  gone, and `open` says `pid not visible in the sandbox` for a Codex row instead of `died`. With
  `CLAUDE_PID` unset (tmux, a plain terminal) and no `SANDBOX_RUNTIME`, the check passes.

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
at 1.5 to 2.3 times it. A6's `audit --monthly` measures them against the ledger. `stop_min` defaults to twice
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

`allow` may add tools, but `check_deadline` refuses a list without all three (from a Codex
review). An empty or misspelled list would otherwise load and deny the handback itself at the stop,
leaving the agent no way to report. Refused as malformed, the file fails closed for the policed
tools and keeps the report path open.

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

### Monthly audit (A6)

`delegation-ledger audit --monthly` is where A1's thresholds (`liveness.toml`) and A2's budgets
(`policy.toml [deadline]`) get retuned. It runs the enforcement checks above over 30 days, then
adds usage sections computed from the ledger and the agent transcripts, which replaces the eval's
scratch scripts. It shows distributions against the current numbers and never suggests new ones:
picking them stays a human call.

| Section | What it answers |
|---|---|
| coverage | how many agents and codex runs it counted, what it left out and why, and how many activations had a readable transcript |
| agents by type | the share of each role; `WARN` when general-purpose is over 25%, since it gets every tool and no report contract |
| teammates, named-spawn denials | is the `team-` prefix becoming a habit, and is A0 fighting real needs? |
| minutes per activation | per role: n, p50, p90 and max against its `[deadline]` budget, and how many ran past the nudge and the stop |
| longest call, longest silence | per kind, against `liveness.toml`'s `tool_min` and `silent_min` |
| reports | `report_ok` per checked role, from each agent's last stop |
| deadline | the agents nudged and the agents stopped, per role |

**An activation runs from a start to the last stop before the next start.** An agent that ends
with plain text in auto mode stops twice (P3 above), so its first stop isn't the end. A Codex run
stops once, so its stop closes it, and a resume that fails before it begins can't stretch the run
before. A stop with no start (an agent older than the ledger, or that failed resume) is counted,
not timed, and so is a start that no stop closed. Claude Code's helper agents aren't delegations,
so the audit skips their rows (an empty `agent_type`, from before the ledger skipped them).

**Agents count by distinct id, activations by start.** On 2026-10-01 reviewer had 30 agents and
34 activations, since a SendMessage resume starts a new activation. A teammate with no recorded
role (a built-in type, so its `agent_type` is its name) counts as general-purpose: it gets the
default policy, which is what the share warns about.

**Probes are excluded with an annotation** (Hayden's call, 2026-10-01). `delegation-ledger exclude
--id <id> --why probe` appends an `exclude` row, and the usage sections leave out every row that
matches all the keys it carries (`--id`, `--session`, `--name`). The exclusions live in the ledger,
beside this machine's data, not in the public repo. A `session_id` that isn't a UUID is hand-fed
hook input (an install check), and it drops out without one.

**`exclude` refuses what it can't match,** so a typo can't silently do nothing. `--session` with
`--name` singles out a main-thread `named-spawn` row, whose id is just `main`. Delegated agents
can't run it: `delegation-ledger` is in `excludedCommands`, which the policy denies them.

**After a hand-run live probe, exclude it.** The canary harness writes to its fixture's own state
dir and never touches the live ledger, but a probe run by hand in a live session does. The probes
already in the main machine's ledger from before A6 are excluded once, by hand. One agent there
reads like a probe by its name but was a real audit run, so it stays in.

**The enforcement checks read every row.** A probe the policy hook missed is still a miss, so the
exclusions apply only to the usage sections. One side effect: the 30-day window shows again a
main-checkout warning that a daily audit already showed.

**Silence is measured from the transcripts when the audit runs.** The longest call runs from a
`tool_use` to its `tool_result`, or to the stop. The longest silence is a gap between entries while
no call is open. Recording both in the stop row would outlive transcript cleanup, but it would put
work on every SubagentStop. `cleanupPeriodDays` is unset, so Claude Code keeps transcripts for its
default 30 days, and a 30-day window loses only its oldest edge; the coverage line counts what it
read. The liveness index can't help, since it is pruned after 7 days.

**Two thresholds are constants, not config.** `GP_WARN_SHARE` (0.25) and `MIN_SAMPLE` (20) sit in
`delegation-ledger`. The Stage 3 plan put the share in `policy.toml`, but a parse error there
blocks every delegated call, and these values only inform. A group with fewer than 20 activations
is marked `too few to retune`.

**Retuning waits for a month of ledger.** `due` asks for `audit --monthly` once the ledger's first
row is 30 days old and so is the last full monthly run (`audit.json` `monthly`), so the first
request lands on 2026-10-30. A run with a narrower `--hours` doesn't count. On 2026-10-01 only
reviewer, researcher and Explore had 20 activations; one reviewer ran past its 20-minute nudge, and
no subagent crossed `tool_min` or `silent_min`.

### Long waits (the watch guard)

**The gap.** A Bash command run with `run_in_background` stops at its `timeout`, 30 minutes by
default and 2 hours at most, and Claude Code then wakes the agent once. The wake-up note says to
start it again with a longer `timeout`, and ends: "If it already had the longest `timeout`
allowed, do not restart it." On 2026-10-02 a lead watching a long detached job hit the 2-hour cap,
followed that note, and ended its turn. Nothing woke it when the job finished. `codex-delegate`
had the same gap: the wrapper was stopped at the cap while Codex ran on. Waiting is liveness, so
the fix is enforcement. `PLAN.md` has the design history and the options weighed.

**The parts.**
- **The waiter, `delegation-ledger wait`.** It records a *watch* (`<state>/watches/<id>.json`; the
  comment above `WATCH_STATES` in `delegation_common.py` documents its fields), polls the
  condition every 15 s with a heartbeat, and exits before the cap with the exact re-arm command,
  so it never gets the "do not restart" note.
  - Conditions: `--pid N` (repeatable: all have exited), `--file PATH` (it exists),
    `--log PATH --done RE` (a matching line; `--fail RE` fails it and `--stale MIN` ends it as
    stale), and `--codex RUN_ID` (Codex has ended; the waiter then runs `codex-delegate finalize`
    itself and decides by the stop row's `exit`).
  - Before it polls, it prints a launch line, flushed: `delegation-ledger: watch <id>. If this
    command is stopped, re-arm with delegation-ledger wait --resume <id> (run_in_background,
    timeout 7200000)`. The guard folds a killed waiter by it.
  - `--max MIN` defaults to 110 and can't go higher, which leaves room for a 5-minute finalize
    under the 120-minute cap. `--drop <id>` ends a watch. `--resume <id>` takes one over, but
    refuses a live waiter someone will hear from: its Claude process is live, whatever its
    session; or, with no process recorded, its session is live (the caller's counts), or it has
    no session either. A live waiter whose Claude process has ended (a crash; the guard then
    marks it `waiter_unheard`), whatever its session, or whose session has ended with no process
    recorded, reports to nobody, so it is taken over, and it steps aside (exit 3) at its next
    beat.
  - A new wait whose condition equals an unresolved watch's takes that watch over and says so,
    once it has, so a rerun after a kill doesn't leave the guard pointing at a second watch. The
    watch is the caller's: in its session, or left by its Claude process in a session that isn't
    live. That covers a rerun after `/clear`, before the guard's first stop adopts it, and a
    caller whose session is `unknown`, matched by its process alone. A caller with neither gets
    a new watch. A codex condition keeps its refusal instead.
  - It records the Claude Code process its exit notifies (`claude_pid` with its procStart) and
    that process's session, both from the parent walk in the known gaps. A waiter outside Claude
    Code records no process, dropping the last waiter's. A new wait with no process found
    records the session `unknown` and says the guard won't see the watch. One with a process but
    no session found records `unknown` and says nothing, since that process's guard adopts the
    watch by the process (`unknown` is never live). A `--resume` outside Claude Code keeps the
    watch's session, drops its `claude_pid` and says nothing, and so does a `codex-delegate
    resume` that takes its run's watch over; only a new watch records `unknown` and warns. `/clear` keeps the process but starts a new
    session id, and the guard adopts the watch into the new session (below). When it ends, it
    records `reported`: true while that process runs, else false.
  - It refuses to run sandboxed, where its pids would belong to another PID namespace. It refuses
    a `--pid` that is pid 1, a kernel thread, another user's, or not running. It refuses a second
    watch on a codex run, naming the existing watch's `--resume` when that watch's waiter is dead
    or its session is gone.
- **The watch guard**, a main-thread Stop hook (`watch-guard`). For each of the session's open or
  acknowledged watches with no live waiter (its pid with its procStart, and a heartbeat no older
  than two polls plus a second; a background shell whose command holds the watch id counts too):
  - a met condition is recorded done and blocks once, since the waiter's notification never came,
    with "Check the result and report it". A codex watch with a stop row is done on exit 0, failed
    otherwise;
  - a codex run that never started (its wrapper died before Codex did, leaving no `codex.pid`) is
    recorded failed and blocks once, saying to run `codex-delegate resume <id>` again, or for a
    first turn to run `codex-delegate run` again, which gets a new run id;
  - anything else is a lapse, which blocks once with the re-arm and drop commands. For a codex run
    that ended without a stop row, it adds that resuming finalizes it;
  - first, it adopts any unresolved watch recorded under its own Claude Code process with another
    session id that is no longer live (a `/clear`), moving it into this session in the commit
    pass and logging it. A live session's watch is never adopted, whatever the pids say, and the
    commit checks the process and the liveness again under the lock. It finds its process by
    the same parent walk as the waiter, so a nested `claude -p` that inherited the lead's
    `CLAUDE_PID` finds itself, not the lead;
  - it also adopts this session's watches whose Claude process has ended (a crash, then
    `claude --continue`), recording itself as their Claude process. A waiter still running there
    reports to a process that's gone, so the watch is marked `waiter_unheard` and blocks once:
    "Watch <id>'s waiter was started by a Claude Code process that has ended, so its exit won't
    reach you. Re-arm it", with the `--resume` command. A dead waiter is a lapse, as above;
  - a watch of this session that ended (done, failed or stale) in the last 7 days while no Claude
    process listened blocks once, "Check the result and report it", and is recorded `reported`.
    Nobody listened when its waiter was `waiter_unheard` or its Claude process has ended, and
    `reported` is false. A waiter records it true when its Claude process runs as it ends, and
    so does the guard for an end it says, so a crash after the news arrived doesn't repeat it.
    A watch with no `reported` at all ended before the field existed, and counts as reported,
    so it never shows.
- **The kill catch**, in the same hook. Each stop reads the transcript on from where the last one
  stopped (`kills/<session>.json` holds the offset), searching the raw bytes for
  `task-notification`. A notice with `<status>killed</status>` at the background time limit blocks
  once per task id. A killed `delegation-ledger wait` or `codex-delegate` folds into the watch
  its launch line names, found anywhere in the first 4 KB of the command's output file. A waiter
  with no launch line there falls back to the watch its `--resume` names, else the one created
  within 120 s after the launch, told apart by `--pid`, `--file` or `--log` when several were.
  Unfolded, a codex kill says Codex keeps running and gives the run's watch to re-arm, or
  `wait --codex` with the run id when it has no watch, or `codex-delegate status` to find the run
  when even the run id is unknown.
- **`codex-delegate`'s own watch.** `run` and `resume` record a `{codex: run_id}` watch whose
  waiter is the wrapper itself. Before Codex starts they print the launch line,
  `codex-delegate: run <run_id>, watch <watch_id>. If this command is stopped, Codex keeps running:
  delegation-ledger wait --resume <watch_id>`, and they heartbeat the watch until the stop row is
  written. At `--max-wait` (110 minutes at most) the wrapper prints the re-arm line and exits 75,
  and Codex runs on. Right after its `Popen` it writes Codex's pid to `<out>/codex.pid`, so a
  wrapper killed before `thread.started` still leaves a run that reads as running. A resume
  refuses while Codex runs, and finalizes an ended turn before it starts the next.
- **The allow rule.** The baseline's `permissions.allow` holds `Bash(delegation-ledger wait *)`,
  so a re-arm never stops at a permission prompt. The waiter must run as a bare command: a `cd`,
  a redirect or `$(...)` keeps the call in the sandbox, where it refuses to run.
- **The session-start nudge.** `delegation-ledger due --hook` names, in its numbered line, up to
  three of the open or acknowledged watches no running session's guard will pick up, oldest
  first, with a count of the rest, and one `wait --resume <id>` and `wait --drop <id>` template
  (`delegation_checks.left_watches`): "<n> watch(es) no running Claude Code session is
  guarding: <id> (<desc>), ... Pick one up with ..." It doesn't say the session ended: after a
  crash and `claude --continue` the session runs on, and a watch with no process recorded may
  never have had a session.
  - A watch is named when nobody will hear from its waiter (`dc.watch_orphaned`) and its
    session isn't running. Nobody will hear from it when the Claude process it was recorded
    under has ended; with no process recorded, when its session isn't live; with neither a
    process nor a session, once its waiter is dead. That holds whatever its waiter's state,
    since a bare waiter can outlive a SIGKILLed Claude Code; a live waiter is marked "its
    waiter is still running".
  - A watch whose session is running (the starting one, or live in another process) isn't
    named, even with its Claude process gone: that session's guard adopts it at its next stop,
    as after a crash and `claude --continue`.
  - A second line names up to three watches that ended (done, failed or stale) in the last 7
    days while no Claude process was listening and aren't reported yet (`dc.ended_unheard`),
    oldest end first: "<n> watch(es) ended while no Claude Code process was listening: <id>
    (<desc>, <state>), ... Check the results." It records the ones it names `reported`, so each
    shows once; a headless `-p` session records nothing. A running session's own (the starting
    one, or one live in another process) are left to its watch guard, which says them to the
    model at its next stop. So after a crash, a plain `claude`, with a new session id, still
    hears of a leftover waiter's end.
  - `delegation-ledger watch` and `open` list those ended watches too, in the same `watches:`
    block as the unresolved ones, until they're reported.
- **The shim logs.** `hooks/watch-guard.sh` appends Python's stderr to `delegation-ledger.err`,
  falling back to `/dev/null` when that file can't be written, so a missing link or an import
  error shows there and in the quick canary instead of leaving the guard silently off. The
  canary runs the shim with a throwaway `XDG_STATE_HOME`, so a guard's routine log line (an
  adoption, say) in the real file can't fail it, and it quotes the last line the shim logged.

**Exit codes.**
- `wait`: 0 done; 1 the job failed (a `--fail` match, its pids exited with another condition
  unmet, or a codex stop row with a nonzero `exit`); 2 the log went stale; 3 this waiter stepped
  aside (its watch was taken over, dropped or deleted); 64 bad usage, including a sandboxed call;
  70 an internal error, or nothing could be decided, with the watch left open; 75 still running at
  `--max`, with the re-arm line.
- Beyond the codes in SKILL §5, `codex-delegate` exits 5 when it stopped at `--max-wait` with
  its watch dropped or taken over, and 75 when it stopped there still running. While Codex runs,
  SIGTERM or SIGHUP makes it append an `interrupted` row with Codex's pid and exit 143, leaving
  the watch open for the guard. Outside that window (before its `Popen`, or while it finishes)
  the signal kills it with no row, and a shell reports 143 for SIGTERM, 129 for SIGHUP.

**How a lead uses it.** Launch every waiter, and every `codex-delegate run` or `resume`, with
`run_in_background` and `timeout: 7200000`, so it exits on its own before the cap:

```bash
delegation-ledger wait --pid 12345 --desc "the build"   # a pid from outside the sandbox
delegation-ledger wait --log build.log --done '^BUILD OK$' --fail '^ERROR'
delegation-ledger wait --resume <id>                     # the re-arm line's command, exactly
delegation-ledger wait --drop <id>                       # stop watching
```

On exit 75, run the printed command exactly. Take the pid from a command run outside the
sandbox: a sandboxed command's pids belong to its own namespace and name another process here.
The waiter refuses one that is pid 1, a kernel thread, another user's or not running, and it
records each pid's command name, so a wrong one that slips through shows in `watch`.

**How a stop runs.** The guard works in three phases, so what it records it also says:
- **Gather**, read-only, within 3 s: verdicts, the transcript scan, launch lookups and log tails.
  Once the budget is spent it takes no new item, and a kill whose launch lookup was cut off gets
  the plain reason.
- **Commit**, in one pass under `kills/<session>.lock` and then `watches/.lock`, each wait
  bounded. The adoptions and every watch's item are one update of the watches, so a busy lock
  means nothing is recorded or said this stop. Each watch is re-read under the lock, so a
  waiter that re-armed meanwhile wins.
- **Print**: one block that numbers every new item, and a `systemMessage` for the lapses it
  acknowledged.

Its once-per-item rules:
- A lapse blocks once. It records `blocked_at`, a digest of the stop's `prompt_id` and
  `last_assistant_message` (`blocked_stop`), and the transcript's size. A later stop (another
  digest) lets it through, marks it acknowledged and warns once; later stops say nothing. A twin
  guard in the same stop gets the same payload, so it neither blocks nor acknowledges. With
  neither field in the payload, a grown transcript marks a later stop, and with no size, 60 s.
- A kill blocks once per task id, recorded in `kills/<session>.json`.
- It decides by these records, not by `stop_hook_active`, so a doubled registration can't loop and
  another hook's block can't swallow this one.
- It fails open. An error on one item is logged to `delegation-ledger.err` and skips that item;
  any other error lets the stop through.
- Where it can't see pids outside its own (a sandboxed run, `pids_visible`: `SANDBOX_RUNTIME=1`,
  or an unseen `CLAUDE_PID` with no live Claude process among its parents), it says nothing,
  since every waiter and Claude process would read as dead. A stale inherited `CLAUDE_PID`
  under a live Claude process doesn't silence it.

**The live re-arm is a manual check.** `claude -p` kills background shells about 5 s after its
final result, so `tests/delegation/run.py` can't hold a wait across turns. A dated item in
`due.toml` asks for it by hand in an interactive session, a month out. A dated item fires by
date only, so the session-start line that says the full canary is due after an upgrade names
the re-arm check too.

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
  is visible. `SANDBOX_RUNTIME=1` is set only inside, and `pids_visible` reads it, so a stale
  inherited `CLAUDE_PID` outside the sandbox isn't taken for it.
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
- **What the watch guard rests on** (the T0 probes, 2026-10-02, on 2.1.286). The version was
  read from the session's own `CLAUDE_CODE_EXECPATH`: `claude --version` printed 2.1.287, because
  it reports the newest installed binary, not the running one. The probes ran in an interactive
  session with a temporary Stop hook in the project's `.claude/settings.local.json`, removed
  afterward:
  - a Stop hook fires on a turn that a background notification started.
    `{"decision": "block", "reason": ...}` keeps that turn going, the reason arrives as a system
    reminder, and the stop after the block carries `stop_hook_active: true`;
  - the Stop payload's keys are `background_tasks`, `cwd`, `effort`, `hook_event_name`,
    `last_assistant_message`, `permission_mode`, `prompt_id`, `scratchpad_dir`, `session_crons`,
    `session_id`, `stop_hook_active` and `transcript_path`. There is no `turn_number` or
    `had_tool_use`, though the docs list them;
  - `background_tasks` lists running tasks only, each with `id`, `type`, `status` and
    `description`, plus `command` for a shell. A killed or finished task drops out, so the list
    can't show a kill. It also holds stale teammates from earlier in the session;
  - a command stopped at its `timeout` gets a notification with `status: killed`, the summary
    `Background command "<description>" was stopped after reaching its background time limit`,
    and a note that ends "If it already had the longest `timeout` allowed, do not restart it.";
  - by the stop of the turn it started, the notice is in the transcript, in one of two shapes. A
    notice that starts a turn is a `type: "user"` entry with
    `origin: {"kind": "task-notification", "producer": "session-task"}`. One that arrives
    mid-turn is an `attachment` entry whose `attachment.type` is `queued_command`, with the notice
    in `attachment.prompt` and the same origin. A `queue-operation` entry sits beside it;
  - `CLAUDE_CODE_SESSION_ID` holds the session id in Bash, inside the sandbox and outside it, and
    `CLAUDE_PID` is set in both;
  - each sandboxed command gets its own PID namespace, so its pids start near 1. Echoed out of it,
    such a pid names pid 1 or a root daemon on the host;
  - a hook edit in a settings file loads in the running session, as the settings docs say.
- **A session id change rewrites the sessions file** (2.1.286, observed 2026-10-02 on a running
  lead). The lead's Claude process started on 2026-09-30 under one session id, which its task
  output dir and an older memory note carry. Its `~/.claude/sessions/<pid>.json` now names the
  id in its current `CLAUDE_CODE_SESSION_ID`, under the same pid. So when a process's session id
  changes, as on `/clear`, the old id leaves `live_sessions()`, which lets the guard adopt only
  from a session that isn't live. The guard checks liveness anyway. The env follows the change
  too, since it named the new id; this doesn't show which of the two updates first.
- **A nested `claude -p` sets its own `CLAUDE_PID` and `CLAUDE_CODE_SESSION_ID`** (2026-10-02, a
  2.1.287 run nested under a 2.1.286 lead, both read from `CLAUDE_CODE_EXECPATH`). Started from
  the lead's Bash, its own Bash calls showed pid 9759 and session `0502d8ef...`, against the
  lead's 36985 and `a8352a78...`. So `claude_identity` takes a nested run's session from its
  env too: the walk finds the nested process, which is its `CLAUDE_PID`.
- **A `claude -p` run writes its own sessions file** (same day), with `entrypoint: sdk-cli` and
  `kind` set. So the guard's parent walk, run from a nested `-p` session's hook, stops at the
  child's process, not its parent's.
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

**Stage 3 (watch) is done.** It was planned in `~/.claude/plans/lets-move-on-to-refactored-pascal.md`,
with A6 in `~/.claude/plans/a6-jazzy-sloth.md`. What's left is data, not code: once the ledger
is a month old, `due` asks for `audit --monthly` ("Monthly audit (A6)" has the date), and its
numbers decide whether A1's thresholds and A2's budgets move.

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
- **Results on 2026-10-01 (A6, 2.1.287):**
  - unit: 302 tests, plus 19 in `tests/setup`;
  - the live harness has no `audit` or `due` case, so A6 adds no live checks, and a full canary
    run still has 65;
  - `audit --monthly` against a copy of the main machine's state, with the five legacy exclusions,
    took 0.31 s and 39 MB: 105 agents and 114 activations over two days, transcripts read for 111;
  - a `reviewer` pass found 7 low defects and nothing higher, and all 7 are fixed:
    - a failed Codex resume stretched the run before it;
    - a role-less teammate escaped the general-purpose share;
    - an activation with no transcript entries read as silent throughout;
    - a damaged ledger head could silence the monthly nudge or fire it early;
    - the transcript cache held full tool output (agent transcripts from 30 days come to 1.7 GB
      here);
    - the docs said helper agents' stops were counted, while the code skips them;
    - the new SKILL.md bullet swallowed the `sandbox-denials` sentence.

    The code fixes each came with a test.
- **Results on 2026-10-02 (the watch guard, T1 to T6):**
  - unit: 469 tests, plus 21 in `tests/setup`. The new files are `test_wait.py` (the waiter, 68)
    and `test_watch_guard.py` (the guard and the kill catch, 60). `test_codex_delegate.py` (35)
    covers the wrapper's watch, and `test_checks.py` (76) the orphaned-watch nudge, the guard's
    canary strings and the shim check. A sandboxed run from this worktree ran 400 of them; the
    69 policy tests need the sandbox off here;
  - the quick canary's string check passes on both 2.1.286 and 2.1.287 with the guard's strings
    added (27 in all). The kill summary isn't one string in the binary, so the canary checks
    `stopped after reaching its background time limit`;
  - the live re-arm across turns is a manual check (see "Long waits").

## Installing on a machine that is already set up

`setup.sh` links everything below. It also **resets** `~/.claude/settings.json` to this repo's
baseline plus `settings.machine.json`, keeping only the top-level keys the baseline doesn't set (see
the README). So a hook that is only in the live file (for example `tmux-state.sh`) is lost unless it
is in the overlay. On a machine without that overlay, do it by hand, **in this order**. The spawn guard and the policy
hook fail closed, so wiring a hook before its script is reachable blocks every delegated call.

1. **Links.**
   - `skills/delegation` → `~/.claude/skills/delegation` (the hook shims call its scripts).
   - `agents/*.md` → `~/.claude/agents/`.
   - `hooks/{agent-spawn-guard,delegation-ledger,delegation-due,subagent-policy,report-check,watch-guard}.sh`
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
5. **The watch guard.** Add the `Stop` entry for `watch-guard.sh` (timeout 5) and the
   `permissions.allow` rule `Bash(delegation-ledger wait *)`. The guard fails open, so its order
   among the Stop hooks doesn't matter. Then smoke-test it from inside a Claude Code session:
   - start a detached `sleep 300` outside the sandbox, and run
     `delegation-ledger wait --pid <its pid> --max 0.05` as a bare command, which exits 75 with
     no prompt;
   - with the sandbox off for that one command (`dangerouslyDisableSandbox`), run
     `echo "{\"session_id\":\"$CLAUDE_CODE_SESSION_ID\",\"prompt_id\":\"x\"}" | bash
     ~/.claude/hooks/watch-guard.sh`, which prints a block naming that watch;
   - `delegation-ledger wait --drop <id>` ends it.

   Why it runs that way: a pipe isn't a bare command, so it matches no sandbox exclusion and runs
   sandboxed, where the state dir is read-only and no pid outside the sandbox is visible, so the
   guard says nothing. A plain terminal has no `CLAUDE_CODE_SESSION_ID`, so the payload would
   name no session.
6. **The due checks.** Add the SessionStart entry (`delegation-due.sh`), then run
   `delegation-ledger canary` outside the sandbox, in the background. When it is green, a new session
   prints nothing unless something is due, and `delegation-ledger due` shows the state. The hook fails
   open, so its order doesn't matter.

**Permissions.** The baseline now has a `permissions` object (the re-arm allow rule), so
`setup.sh` replaces a live `permissions` object with the baseline's, and `merge-settings.py`
names the reset on stderr. `setup.sh` moves the replaced copy to
`~/.claude/backups/pre-dotclaude-<ts>/` and prints "backing up" as it does, so a lost rule is
recovered from there. Personal permission rules go in `settings.machine.json`, whose lists
append to the baseline's.

**If Claude Code won't start** because the sandbox can't (a missing bwrap after an upgrade, say), set
`"enabled": false` under `sandbox` in `~/.claude/settings.json` with an editor. That also takes
delegated agents' Bash away, until the sandbox is back.

Observed on the 2026-09-30 install: skill links and settings hooks took effect in the running session
at once. Agent definitions reloaded a little later: the first `Explore` spawn after linking still got
the built-in. So check the override with a fresh spawn, or in a new session.
