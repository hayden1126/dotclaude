# Delegation hardening

Delegated agents drifted out of scope and seemed to stall. This is the design that fixes it, what
ships now, and what comes next. The skill that operators follow is `skills/delegation/SKILL.md`. This
doc holds the reasoning and the verified facts behind it.

## Principle and evidence

Prose covers purpose and judgment. Enforcement covers authority, acceptance and liveness. Scope is
**coarse**: an agent's reach comes from its role (its tools) and its working directory, and never
from parsing its brief. Hook input identifies an agent only by `agent_id` and `agent_type`, so a hook
could not read a per-task scope even if we wanted it to.

The 2026-09-29 evaluation covered 384 agents over 10 days. Its data stays local in
`~/scratch/delegation-eval/` and is not in git, because it names agent IDs from other projects. It
found:
- **Drift:** 12 drift or instruction-violation cases. Every one was an agent given a scope in prose
  while it held full Bash.
- **"Stalls":** these were long, silent teammate turns (10 of 118 teammates went over 30 minutes), not
  lost reports. Ordinary subagents lost 1 report in 266.

## What ships (Stage 1)

| Piece | File | Enforces or persuades |
|---|---|---|
| `Explore`, overriding the built-in | `agents/Explore.md` | Enforces: Read, Grep, Glob, WebFetch and WebSearch only, on sonnet, CLAUDE.md skipped. The built-in keeps Bash and asks for read-only in prose only |
| `researcher` | `agents/researcher.md` | Persuades: it has Bash, so read-only holds by prose only until Stage 2 |
| `reviewer` | `agents/reviewer.md` | Enforces: Read, Grep and Glob only |
| `writer` | `agents/writer.md` | Enforces: `isolation: worktree`, and no Agent tool |
| Spawn guard | `hooks/agent-spawn-guard.sh`, `skills/delegation/scripts/agent-spawn-guard` | Enforces: denies a `writer` spawn without `isolation` on the call. Fails closed |
| Ledger | `hooks/delegation-ledger.sh`, `skills/delegation/scripts/delegation-ledger` | Observes: a pointer row per agent start and stop, plus `report_ok`. Fails open |
| Brief and report | `skills/delegation/BRIEF.md`, `report.schema.json` | Persuades (the brief); checks (the schema, via the ledger and codex-delegate) |
| Codex wrapper | `skills/delegation/scripts/codex-delegate` | Enforces: model gate, sandbox, memory cap, timeout, schema, and a recursive model audit |
| `worktree.baseRef: "head"` | `settings.json` | A writer's worktree branches from the current branch, not from `main` |

### Where enforcement stops (known gaps)

- **Team bypass.** With agent teams on, a named spawn starts as a teammate in the main checkout.
  The docs: "An `isolation` value in the subagent's frontmatter doesn't prevent it". The spawn guard
  closes this for `writer` only.
- **Writer escape.** The writer's Bash can still write outside its worktree through a subprocess
  (for example `python3 -c open(...)`). The worktree guard checks only command text and working
  directory. Stage 2's sandbox is the fix, and it needs a live test of the worktree's writable root.
- **Hook timeout.** A hook timeout is non-blocking, so a spawn guard that hangs past 10 s lets the call
  through. It is a stdlib script that makes no network calls.
- **general-purpose spawns** are logged, not constrained. Stage 2 decides whether to require a role.
- **The `researcher` shell** is bounded by prose only until the sandbox lands.
- **The live harness can't reach the team bypass.** A named spawn becomes a teammate only
  in an interactive session with agent teams on, and `run.py` uses `claude -p`. What is
  covered:
  - the guard's decision is unit-tested;
  - its denial is tested live, through the fixture's hook entry, which calls the guard script
    directly rather than the installed shim;
  - the install check below covers the installed shim.

  A named, isolated writer staying a subagent in an interactive team session is untested.
  The Stage 3 canary needs an interactive step for it.

## Verified facts the design rests on

All were checked on 2026-09-29 against Claude Code 2.1.285 and Codex CLI 0.154.

- **Grep and Glob:** on Linux and WSL they are absent by default. They come back for a subagent that
  lists them in `tools` and leaves out Bash
  ([tools-reference](https://code.claude.com/docs/en/tools-reference), "Glob tool behavior").
- **Explore override:** "A user or project subagent named `Explore` overrides the built-in and keeps
  its own `model` field" ([sub-agents](https://code.claude.com/docs/en/sub-agents)). The live harness
  shows this: under a haiku lead, the Explore transcript runs on sonnet.
- **Built-in Explore** (read from the 2.1.285 binary):
  - it denies only the edit tools, keeps Bash, and has `omitClaudeMd: true` and `model: inherit`;
  - its prompt forbids writes in prose ("STRICTLY PROHIBITED");
  - its own description says not to use it for review or open-ended analysis.
- **Team bypass:** "a subagent that Claude spawns from the main conversation with a `name` launches as
  a teammate instead, unless the call is a fork or passes `isolation` on the call itself"
  ([sub-agents](https://code.claude.com/docs/en/sub-agents)).
- **Worktree base:** `isolation: worktree` branches from the default branch unless
  `worktree.baseRef` is `"head"` ([worktrees](https://code.claude.com/docs/en/worktrees), "Choose the
  base branch").
- **Hook precedence:** "When multiple PreToolUse hooks return different decisions, precedence is
  `deny` > `defer` > `ask` > `allow`". Exit 2 routes the same way as deny
  ([hooks](https://code.claude.com/docs/en/hooks)).
- **Hook events:**
  - SubagentStart fires "each time an in-process agent team teammate handles a new message", so the
    ledger folds rows by `agent_id`;
  - the SubagentStop input carries `last_assistant_message` and `agent_transcript_path`;
  - in `-p` mode a folder is treated as trusted, so project hooks run
    ([hooks](https://code.claude.com/docs/en/hooks)).
- **Silent failure modes:**
  - Claude Code ignores an agent frontmatter field it doesn't recognize, without reporting an
    error;
  - a hook that errors (any exit other than 2) or times out doesn't block.

  So enforcement can switch off without a signal. That is why `test_agents.py` checks field names
  against the documented list, why the guard fails closed, and why there is an upgrade canary.
- **Teammate reporting:** teammates report to the lead through `teammate-message` and
  `idle_notification` events, not task notifications. A liveness check that watches only task
  notifications misses them.
- **Stall timeout:** `CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS` (default 10 minutes) aborts a subagent that
  makes no progress and reports the stall to its parent
  ([env-vars](https://code.claude.com/docs/en/env-vars)).
- **Bash sandbox:**
  - it confines Bash and its subprocesses, and subagents "use the same sandbox configuration";
  - it needs bubblewrap and socat, and on WSL2 the seccomp filter, without which a sandboxed command
    can launch Windows binaries;
  - none of those is installed here ([sandboxing](https://code.claude.com/docs/en/sandboxing)).
- **Codex sub-agents:**
  - a `spawn_agent` without a model inherits the parent's model (tested);
  - the `agents.default_subagent_model` config key exists (tested). It is deliberately
    **not** in `codex/config.toml`: with the parent pinned to Sol, inheritance already covers
    children spawned without a model, and `merge-config.py` manages only top-level keys (a
    dotted key would need nested-table merging). `codex-delegate` passes it with `-c` as a
    second safeguard;
  - an explicit model argument still overrides both;
  - a child can't get its own sandbox (`codex-rs/core/src/agent/child_config.rs`);
  - a child rollout's first `session_meta` carries `payload.parent_thread_id`;
  - `--json` emits no heartbeat event;
  - `--output-schema` applies per turn, so resume must pass it again.

## Adopt, copy or build (survey, 2026-09-29)

No existing setup was worth building on, so we built a thin layer on native controls and copied five
patterns:
- **Per-agent scope:** nothing enforces it. agent-pd only detects.
- **Agent collections** (wshobson, VoltAgent) persuade only, and their reviewers carry Bash or Write.
- **Orchestrators:** ruflo/claude-flow is hype, claude-squad is AGPL, and vibe-kanban and Conductor
  follow a different architecture.
- **codex-plugin-cc** is kept for interactive `/codex:*` use, not for scripted delegation:
  - it leaves the model unset;
  - it kills its jobs at session end;
  - jobs wedge in "running" (#391);
  - it hangs when run in a worktree (#367).

| Source | License | What we took | Where |
|---|---|---|---|
| kenryu42/cc-safety-net | MIT | Fail closed on any exception, always with a reason; the block-intent vocabulary | spawn guard; `BRIEF.md` stop rule |
| stefanprodan/cctop | Apache-2.0 | Liveness rules: `~/.claude/sessions/<pid>.json` plus `/proc`, and the transcript's last entry | `delegation-ledger open`; Stage 3 heartbeat |
| openai/codex-plugin-cc `job-control.mjs` | Apache-2.0 | Phase inference from the event log | `codex-delegate status` |
| obra/external-subagents | none (idea only) | A pending row before launch; idle minutes | `codex-delegate` |
| Parable, via ldayton/Dippy | MIT | Stdlib bash parser (planned) | Stage 2 hook |
| oscarthroedsson/breadcrumb | MIT | SubagentStop rejection cap of 2 (planned) | Stage 2 report check |

All of these are reimplemented; no code was copied verbatim. dcg is out: its license rider excludes
anyone acting for Anthropic or OpenAI.

## Next stages

**Stage 2 (enforce):**
- **Native sandbox, session-wide.** Install bubblewrap, socat and the seccomp filter (`npm i -g
  @anthropic-ai/sandbox-runtime`) and set `failIfUnavailable: true`. Run a soft week first with
  `allowUnsandboxedCommands: true`, so a retry goes through a prompt, then set it to `false`. Add
  Read/Edit deny rules for `~/vault/**` and credential paths, which feed bubblewrap, and a network
  allowlist.
- **A subagent-only PreToolUse hook** (active when `agent_id` is present):
  - it enforces agent_type plus cwd scope;
  - it denies MCP write and send tools and `git push`;
  - it parses commands with Parable and fails closed.
- **A SubagentStop and SubagentHandback schema check,** capped at 2 rejections.
- **Decide on the general-purpose rule** from the ledger's data.

**Stage 3 (watch):**
- A cctop-style heartbeat in `tmux-state.sh`.
- An upgrade canary: rerun `tests/delegation/run.py` after each Claude Code upgrade. It checks that the
  override, the guard and the hook fields still bind.
- A monthly audit.

## Tests

- **Unit:** `python3 -m unittest discover -s tests/delegation -t tests/delegation`. It uses no model
  calls; the codex-delegate tests use a fake `codex` on `PATH`.
- **Live:** `python3 tests/delegation/run.py --runner claude` runs 4 short `claude -p` sessions (sonnet;
  the reader case uses a haiku lead). `--runner codex` runs one short Terra run. Both use a disposable
  fixture, install nothing, and isolate the ledger through `XDG_STATE_HOME`. Pick claude cases with
  `--cases`.
- **Results on 2026-09-29:**
  - claude: 19/19 (reader, researcher, writer in a worktree with the main checkout unchanged, the
    guard's denial, ledger pairs);
  - codex: 7/7, plus a live `resume`.

## Installing on a machine that is already set up

`setup.sh` links everything below. It also **resets** `~/.claude/settings.json` to this repo's
baseline, and the live file may hold hooks that aren't in the baseline (for example
`tmux-state.sh`). On a live machine, do it by hand, **in this order**. The spawn guard fails
closed, so if its hook is wired before the guard script is reachable, every Agent spawn is
blocked.

1. **Links.** `skills/delegation` to `~/.claude/skills/delegation` (the hook shims call its
   scripts). `agents/*.md` into `~/.claude/agents/`. `hooks/agent-spawn-guard.sh` and
   `hooks/delegation-ledger.sh` into `~/.claude/hooks/`. `codex-delegate` and
   `delegation-ledger` into `~/.local/bin/`.
2. **Check the guard before wiring it.** `echo '{"tool_name":"Agent","tool_input":{"subagent_type":"writer"}}' | bash ~/.claude/hooks/agent-spawn-guard.sh`
   must print a deny. The same payload with `"isolation":"worktree"` must print nothing.
3. **Last, the settings.** Add the three hook entries (PreToolUse `Agent|Task`, SubagentStart,
   SubagentStop) and `"worktree": {"baseRef": "head"}` to the live `~/.claude/settings.json`.
   Then start a new session, spawn an `Explore` agent, and confirm the ledger got its start and
   stop rows (`delegation-ledger tail`).
