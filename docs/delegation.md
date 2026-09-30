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
   - It catches the obvious forms; layer 1 catches the rest.
3. **The report check** covers acceptance. It sends a malformed report from one of our roles back
   to the agent at most twice.
4. **Observation.**
   - The ledger records every start, stop and denial.
   - `audit` flags a hook that stopped seeing agents, and a writer run that coincided with a
     main-checkout change.
   - `sandbox-denials` lists what the sandbox refused.

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
| Ledger | `hooks/delegation-ledger.sh`, `skills/delegation/scripts/delegation-ledger` | Observes: start and stop rows, `report_ok`, denial rows, the main-checkout hash for a worktree agent; `audit`; `sandbox-denials`. Fails open |
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
  - the live enforcement sources in `~/dotclaude`.
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
  denies it as `unknown-command`. Running the creating step as its own call works. Seen once in the
  live harness (2026-09-30), from a writer that chained its steps.
- **Network filtering is by hostname only,** so domain fronting is possible.
- **A cloned repo's committed `sandbox.filesystem.allowWrite`** widens that repo's own sandbox
  (cc-safety-net RR-11). This is noted, not policed.
- **Hook timeout.** A hook timeout is non-blocking. The settings command's `timeout 8` and the
  script's 5-second alarm both deny first.
- **Teammates are checked by hand.** `-p` still can't create a teammate (2.1.286: a named spawn
  there runs as a plain subagent), so the live harness can't cover one. The teammate facts below
  come from a live session. A teammate's meta.json appeared about 0.5 s after its transcript
  began and before its first tool call; a first call that beat it would get the default rules.
- **Vault.** There is deliberately no vault read deny. A session-wide deny would break hq's vault
  routing and vault's own sessions, and Bash writes to vault from other sessions are already
  outside the write roots.

## Stage 3

Stage 3 makes the setup check itself instead of relying on someone remembering. The plan is in
`~/.claude/plans/lets-move-on-to-refactored-pascal.md`. Step 0 and A0 are done.

### Teams are off by default (A0)

Every named spawn silently became an in-process teammate. The 2026-09-30 re-evaluation found 57
teams on this machine, all implicit `session-<id>` teams, and 86 of the 89 teammates recorded in
`~/.claude/teams/*/config.json` were general-purpose. Of 308 teammate messages, 293 went to the lead. Of the 15 peer-to-peer ones, 13
were report-delivery churn between nested agents, so 2 were real coordination. Teammates also
caused 10 of the 11 eval stalls (34 to 520 minutes). So a team bought almost nothing and cost the
most.

`agent-spawn-guard` now denies a named spawn unless its name starts with `policy.toml` `[spawn]
team_prefix` (`team-`). A fork, or a spawn that passes `isolation` on the call, may still be
named, and the writer rule keeps priority. The denial (intent `use_alternative`) says to drop the
name and SendMessage the returned id. It is recorded as a `named-spawn` policy row, so the
monthly audit can tell whether the guard is fighting real needs. SKILL §1 says when a team earns
the prefix.

### What Step 0 found

- **Workflow agents are covered** (P1). Their hook input carries `agent_id`, and the policy
  denied one's `git push`. The inference Stage 2 rested on holds.
- **The stall timer doesn't catch an agent inside one long tool call** (P2). A 100-second call
  finished under a 45-second timer. So liveness (A1) must track the time since a tool started,
  not only the time since the last event.
- **The harness never isolated the code under test.** `claude -p` loads user settings, so the
  installed copy of every hook ran beside the checkout's copy. A regression in the checkout could
  pass because the installed copy enforced the same rule. It surfaced when report-check ran twice
  per stop (below). The harness now passes `--setting-sources project,local`, and the fixture
  carries the `env` and `teammateMode` it needs from the user tier.
- **report-check could loop forever under a duplicated hook.** Each registration bumped the
  counter, and giving up cleared it, so the attempts cycled 1, 2, 1, 2 and every stop still
  carried a block. An Explore agent that kept refusing the JSON block looped for 18 stops on
  2.1.286. Once it gives up, report-check now stays given up for that agent, for a day. The cost:
  a later SendMessage resume of that agent keeps its id, so a bad report then passes unchecked
  (the ledger still records `report_ok: false`).
- **A teammate's `agent_type` is its name** (P4, 2026-09-30). A `team-probe` spawned as
  `researcher` arrived as `agent_type: "team-probe"`. Its `agent_id` was present and the policy
  denied its `git push`, but it got the default rules, not the researcher allowlist. The role is
  in meta.json's `customAgentType` (beside `taskKind: "in_process_teammate"`). The policy and the
  ledger now resolve the role through `delegation_common.agent_role`. The ledger also records the
  teammate's `name`.
- **Nested worktrees.** A lead session in a worktree nests its agents' worktrees inside it. The
  policy's cwd fallback took the first `/.claude/worktrees/`, which made the lead's whole
  worktree the agent's root; it now takes the last. The protected area (`main_root`) stays the
  outermost checkout, because it holds both the lead's worktree and the real main checkout.
- **The ledger anomalies are not coverage gaps** (P3). The unpaired stops from 05:17Z to 06:24Z
  on 2026-09-30 were Claude Code helper agents, logged before the empty-type skip was installed.
  The one general-purpose stop without a start began at 05:16:28Z, 30 seconds before the
  ledger's first row. A researcher's two stops were legitimate: its plain-text reply stopped it
  once, then Claude Code injected `[handback-send-enforce] Your report has not been delivered`
  and it stopped again after `SubagentHandback`. `fold` already keeps the latest row per id, so
  counts must use distinct ids, not stop rows.
- **Two test-suite bugs.** A slug built by replacing only `/` and `.` failed about one run in
  five. And sandboxed from a checkout under `.claude/worktrees/`, the policy tests have nowhere
  clean to build their fake homes, so they now fail with one message saying so.

## Verified facts the design rests on

Checked against Claude Code 2.1.285 and Codex CLI 0.154, then re-run on 2.1.286 with the full live
harness. "Probe" means a live `claude -p` run with a real sandbox on 2026-09-30. Where the docs and
the binary disagree, the binary wins.

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
  - all 87 recorded teammates in `~/.claude/teams/*/config.json` ran with `backendType: in-process`;
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
  far past the timer; the Stage 3 liveness state (A1) has to see it.
- **Workflow agents** (probe on 2.1.286, case `workflow`): their PreToolUse, PostToolUse and
  SubagentStart carry `agent_id`, with `agent_type: "workflow-subagent"`, and the policy denied
  one's `git push`. Under `-p` the Workflow tool first asks for review ("Review dynamic workflow
  before running"), so the harness pre-allows it.
- **Teammate identity** (live session, 2.1.286): a teammate's hook `agent_type` is its name. Its
  meta.json has `agentType` (the name), `name`, `customAgentType` (the role it was spawned as),
  `taskKind: "in_process_teammate"` and `teamName`. The agent definition still binds (model and
  tools). `agent_id` looks like `ateam-probe-<hex>`.
- **meta.json timing:** a plain subagent's meta.json doesn't exist yet at SubagentStart; it does by
  SubagentStop. A named plain subagent's meta.json carries `name`.
- **A doubled SubagentStop:** in auto mode, an agent that ends with plain text stops, then Claude
  Code injects `[handback-send-enforce]` and it stops again after `SubagentHandback`. Each stop
  fires the hook.
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
| stefanprodan/cctop | Apache-2.0 | The liveness rules: `~/.claude/sessions/<pid>.json` plus `/proc`, and the transcript's last entry | `delegation-ledger open` |
| openai/codex-plugin-cc `job-control.mjs` | Apache-2.0 | Phase inference from the event log | `codex-delegate status` |
| obra/external-subagents | none (idea only) | A pending row before launch; idle minutes | `codex-delegate` |

Apart from Parable, everything is reimplemented. dcg is out: its license rider excludes anyone
acting for Anthropic or OpenAI.

## Next

**Stage 3 (watch)** is planned in `~/.claude/plans/lets-move-on-to-refactored-pascal.md`, which
replaced the bullets that stood here. Its order: Step 0 probes, then A0 (named spawns off),
A4 and A5 (due nudges, a one-command canary), A1 (per-agent liveness state), A3 (one watch view),
A2 (deadline nudge, then hard stop), A6 (monthly audit). Step 0 and A0 are done; see
"Stage 3" above.

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
- **Results on 2026-09-30 (Claude Code 2.1.286):**
  - unit: 158 tests;
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

## Installing on a machine that is already set up

`setup.sh` links everything below. It also **resets** `~/.claude/settings.json` to this repo's
baseline, and the live file may hold hooks that aren't in the baseline (for example
`tmux-state.sh`). On a live machine, do it by hand, **in this order**. The spawn guard and the policy
hook fail closed, so wiring a hook before its script is reachable blocks every delegated call.

1. **Links.**
   - `skills/delegation` → `~/.claude/skills/delegation` (the hook shims call its scripts).
   - `agents/*.md` → `~/.claude/agents/`.
   - `hooks/{agent-spawn-guard,delegation-ledger,subagent-policy,report-check}.sh` →
     `~/.claude/hooks/`.
   - `codex-delegate`, `delegation-ledger` and `gh-public` → `~/.local/bin/`.
2. **Check the scripts before wiring them.**
   - The spawn guard, with
     `echo '{"tool_name":"Agent","tool_input":{"subagent_type":"writer"}}' | bash ~/.claude/hooks/agent-spawn-guard.sh`,
     must print a deny.
   - The policy, with `{"agent_id":"x","tool_name":"Bash","tool_input":{"command":"git push"},"cwd":"/tmp"}`
     through `bash ~/.claude/hooks/subagent-policy.sh`, must print a deny. It denies Bash until the
     sandbox block is in, which is expected.
3. **The hook entries.** Add the PreToolUse entries (`*` for the policy, `Agent|Task` for the guard,
   `SubagentHandback` for the report check) and the SubagentStart and SubagentStop entries to the live
   `~/.claude/settings.json`, copied from the baseline. Then spawn an `Explore` agent and check:
   - its transcript runs on sonnet;
   - the ledger has start and stop rows (`delegation-ledger tail`);
   - `delegation-ledger audit` says the policy hook saw it.
4. **The sandbox.** Add the `sandbox` block and `teammateMode`, then **restart Claude Code**: the
   dependency check runs only at startup. In the new session:
   - `claude sandbox status` shows enabled;
   - a Bash write outside cwd fails;
   - `cat ~/.config/gh/hosts.yml` fails;
   - `git fetch` and `gh pr list` still work, through the exclusion;
   - the prompts are unchanged.

**If Claude Code won't start** because the sandbox can't (a missing bwrap after an upgrade, say), set
`"enabled": false` under `sandbox` in `~/.claude/settings.json` with an editor. That also takes
delegated agents' Bash away, until the sandbox is back.

Observed on the 2026-09-30 install: skill links and settings hooks took effect in the running session
at once. Agent definitions reloaded a little later: the first `Explore` spawn after linking still got
the built-in. So check the override with a fresh spawn, or in a new session.
