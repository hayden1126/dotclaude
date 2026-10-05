# My Claude Code setup

A portable snapshot of my global [Claude Code](https://docs.claude.com/en/docs/claude-code/overview)
configuration: global instructions, the skills, agents and hooks Hayden and Friends authored, durable-state templates,
settings, and the plugins I install. Run `./setup.sh` on a fresh machine and end up with the
same setup.

This is a deliberately lean, principle-driven config. It vendors only what Hayden and Friends wrote or curated,
plus one pinned third-party file: Parable, the MIT bash parser the delegation policy uses
(`skills/delegation/scripts/vendor/`).
Plugin-owned content (plugin skills, agents, hooks) is installed from the plugins' own
marketplaces, not copied here, so it never goes stale.

## Quickstart

```bash
git clone https://github.com/hayden1126/dotclaude.git
cd dotclaude
./setup.sh
claude login        # one-time auth
```

On Linux and WSL2, install `bubblewrap` and `socat` first (`sudo apt install bubblewrap socat`).
The baseline turns Claude Code's Bash sandbox on with `failIfUnavailable`, so without them Claude
Code refuses to start (`setup.sh` warns).

`setup.sh` is idempotent. Existing real files in `~/.claude/` are backed up to
`~/.claude/backups/pre-dotclaude-<timestamp>/`, then replaced with symlinks back to this repo,
so edits in either place stay in sync. The one exception is `settings.json`: it is **copied**, not
symlinked, because the Claude Code runtime rewrites it (persisting managed keys like
`extraKnownMarketplaces`). A symlink would push that churn back into the repo; the copy keeps the
repo file as a curated baseline while the runtime owns its own copy.

Each run replaces that copy, so a value added to a key the baseline sets is lost. Settings that belong
to one machine, such as hooks for its own scripts or `sandbox.excludedCommands` for its own tools, go
in `~/.claude/settings.machine.json` instead. It isn't in this repo; `setup.sh` installs the baseline
with it merged in. Objects merge key by key, lists append (skipping items already there), and any
other value replaces the baseline's (`merge-settings.py`). Top-level keys only the live copy sets
(what `/config`, `/model` and auto mode write, such as `autoMode` and `model`) are kept. `setup.sh`
names every live value the baseline overrides (such as `effortLevel`) and every live hook command
it drops; put a value in the overlay to keep it. The baseline now owns a `permissions` object, so
`setup.sh` replaces the live one (`merge-settings.py` names it on stderr): personal allow rules go
in `settings.machine.json`, whose lists append.

A typical overlay sets a preference and the machine's own tools:

```json
{
  "effortLevel": "high",
  "sandbox": {"excludedCommands": ["mytool *", "mytool"]}
}
```

`effortLevel` replaces the baseline's `medium`. `excludedCommands` appends to the baseline's list:
name your own CLIs that must run outside the sandbox (say, ones that write outside the project),
one pattern per command shape (`mytool *` for calls with arguments, `mytool` for the bare call).
A pattern must match the whole command, so a call through a pipe, `&&` or `cd` still runs
sandboxed.

The baseline's `permissions` deny destructive git and ask before `git push`, in auto mode too.
Denied: force-push, `reset --hard`, `reset --merge` and `git clean -f`, plain or through `git -C`,
plus a `bash -c` whose text has `git push` then `--force`, or `git reset` then `--hard`. Asked:
`git push` and `git -C <dir> push` with any arguments, so a force the deny rules miss (`+branch`,
`-uf`) still prompts. Everything else goes to auto mode's classifier: other wrappers (any other
`bash -c`, such as one running `push -f`, and `bash -lc`, `sh -c`, `eval`), git global options
other than `-C` (`-c k=v`, `--git-dir`, `--no-pager`), soft, mixed and `--keep` resets, and
`checkout`, `switch`, `restore` and `revert`. Why rules at all: on 2.1.288, auto mode ran a
force-push and a `reset --hard` on a dirty tree when the prompt named them.

`rm` never asks. Ask rules for `rm -r` and `rm -f` stopped sessions and stalled delegated writers
mid-task, and a hook can't exempt agents from them: an ask rule prompts even when a PreToolUse
hook returns `allow`. The sandbox bounds where `rm` can write (the project, temp and the cache
dirs), `subagent-policy` keeps a delegated `rm -r` in its root or temp, and git holds committed
work. What's exposed: uncommitted work in the project, and an `rm` run outside the sandbox, which
only auto mode's classifier sees. To bring the asks back on one machine, put this in
`settings.machine.json` and re-run `setup.sh`:

```json
{"permissions": {"ask": ["Bash(rm -*r*)", "Bash(rm -*R*)", "Bash(rm -*f*)",
                         "Bash(rm * -*r*)", "Bash(rm * -*R*)", "Bash(rm * -*f*)"]}}
```

A rule's `*` spans words, so some safe commands are caught too. Denied: a `git -C` command whose
message mentions a guarded phrase (commit with `-F <file>`, or from inside the repo), and a
`git clean -n` dry run on a path containing `f`. Asked: any `git -C` command with `push` as a
later word, such as `git -C <dir> stash push`. Permission rules apply to delegated agents as well,
though `subagent-policy` refuses a writer's `git -C` outside its worktree before the push rule
sees it.
`tests/delegation/test_settings.py` pins each rule with a case only it catches.

## What's in here

| Path | What it is | Installs to |
|---|---|---|
| `CLAUDE.md` | Global instructions: working partnership, boundaries, voice, the explore -> spec -> plan -> execute -> verify -> review workflow | symlink `~/.claude/CLAUDE.md` |
| `settings.json` | Hooks, status line, env vars, enabled plugins, permission rules, and the Bash sandbox (curated baseline; see docs/delegation.md for the sandbox) | **copy** to `~/.claude/settings.json` (runtime-managed, not symlinked), merged with `~/.claude/settings.machine.json` when present |
| `merge-settings.py` | Merges the machine overlay into the baseline and keeps the live file's own top-level keys, for `setup.sh` | run by `setup.sh` |
| `git/sandbox-stubs.ignore` | Git ignore patterns for the `/dev/null` mounts the Bash sandbox puts over protected dotfiles a repo lacks (they break `git add -A`) | upserted by `git/install-ignore.py` between markers in the global git excludes file (`core.excludesFile`, else `~/.config/git/ignore`); Linux only |
| `skills/` | The skills I authored: `coding-practices`, `research-discipline`, `research-sourcing`, `writing-voice`, `staged-reader-review`, `ebook-extract`, `deck-production`, `vetting-sources`, `handoff`, `frontend-ui-discipline`, `ui-alignment`, `delegation` | symlink per dir into `~/.claude/skills/`; a skill's `scripts/` CLI also symlinks into `~/.local/bin` when that dir exists (`deck-production` ships `deckkit`; `delegation` ships `codex-delegate`, `delegation-ledger` and `gh-public`); the portable ones (`CODEX_SKILLS` in `setup.sh`) also link into `~/.codex/skills/` |
| `agents/` | Delegation roles: `Explore` (overrides the built-in with a no-shell reader), `researcher`, `reviewer`, `writer`; see docs/delegation.md | symlink per file into `~/.claude/agents/` |
| `hooks/agent-spawn-guard.sh` | PreToolUse(Agent) guard: denies a `writer` spawn that doesn't pass `isolation` on the call, and a named spawn without the `team-` prefix; fails closed | symlink `~/.claude/hooks/agent-spawn-guard.sh` |
| `hooks/delegation-ledger.sh` | SubagentStart/SubagentStop hook: appends a pointer row per delegated agent to the delegation ledger; as a PostToolUse hook, sends a delegated agent its deadline nudge; never blocks | symlink `~/.claude/hooks/delegation-ledger.sh` |
| `hooks/delegation-due.sh` | SessionStart hook: runs the cheap delegation checks in the background (the quick canary on a new Claude Code version, a daily audit) and shows a line only when something is due, or when a watch needs Hayden: one whose waiter's exit reaches nobody, or one that ended while no Claude process listened; fails open | symlink `~/.claude/hooks/delegation-due.sh` |
| `hooks/subagent-policy.sh` | PreToolUse(*) policy for delegated agents only (rules in `skills/delegation/policy.toml`): no leaving the sandbox, no destructive git, no MCP writes, protected paths, the researcher allowlist, writers held to their worktree; fails closed | symlink `~/.claude/hooks/subagent-policy.sh` |
| `hooks/watch-guard.sh` | Stop hook (main thread): blocks a stop once when a `delegation-ledger wait` watch has lapsed or a background command was killed at its time limit, with the re-arm command (`skills/delegation/scripts/watch-guard`); fails open | symlink `~/.claude/hooks/watch-guard.sh` |
| `hooks/report-check.sh` | PreToolUse(SubagentHandback)/SubagentStop hook: sends a delegated role's malformed report back, at most twice; fails open | symlink `~/.claude/hooks/report-check.sh` |
| `hooks/handoff-reminder.sh` | UserPromptSubmit hook: on a wrap-up / handoff / clear-memory signal, reminds me to invoke the `handoff` skill instead of improvising it; a shim over `hooks/handoff_reminder.py`, which holds the classifier | symlink `~/.claude/hooks/handoff-reminder.sh` and `handoff_reminder.py` |
| `hooks/session-title.sh` | UserPromptSubmit hook: sets the terminal tab title to `[<repo>] <label>` via `sessionTitle`, so tabs are tellable apart; the label comes from the Stop-hook Haiku cache (`.title.txt`), falling back to the current prompt's first line | symlink `~/.claude/hooks/session-title.sh` |
| `hooks/stop-ring.sh` | Stop hook: plays the Windows notify sound when a session you see finishes (a tab, a plain terminal or a mapped background session), not a subagent, an unmapped background session, a `claude -p` run, or a turn that ends with an agent or shell still running for it; logs each decision to `ring.log` | symlink `~/.claude/hooks/stop-ring.sh` |
| `hooks/notify.sh` | Notification(permission_prompt) hook: pops a Windows toast, resolving the toast path per platform (WSL via `wslpath`, native Windows git-bash via `cygpath`), and rings like `stop-ring.sh` | symlink `~/.claude/hooks/notify.sh` |
| `hooks/tmux-state.sh` | Prompt, tool, Stop and Notification hook: sets `@claude_state` (busy, wait, idle) on the tmux window the session is shown in, for the indicator in `tmux/claude.conf`; does nothing outside tmux | symlink `~/.claude/hooks/tmux-state.sh` |
| `hooks/session-pane.sh` | Sourced by the three hooks above, not a hook: finds the tmux pane a session is shown in, and whether a person sees it | symlink `~/.claude/hooks/session-pane.sh` |
| `hooks/session-summary.sh` | Stop hook: regenerates a 1-2 sentence session summary via a direct Haiku Messages-API call (Claude subscription OAuth token, stdlib urllib, no API key/jq), detached so it never blocks; caches the summary to `<config-dir>/session-summaries/<session_id>.txt` for the status-line widget and a short (`<=32`-char) tab label to `<session_id>.title.txt` for `session-title.sh` | symlink `~/.claude/hooks/session-summary.sh` |
| `templates/` | `SPEC.md`, `PLAN.md`, `STATUS.md` scaffolds for full-lane work that survive `/clear` | symlink per file into `~/.claude/templates/` |
| `codex/` | Codex CLI config (config.toml baseline + AGENTS.md + merge-config.py); see docs/codex.md | symlink `AGENTS.md` into `~/.codex/`; merge `config.toml`'s keys into the local `~/.codex/config.toml` (Codex writes to it, so it is never linked; `auth.json` stays local) |
| `notify-toast.ps1` | Windows toast script that `notify.sh` renders for the Notification hook | symlink `~/.claude/notify-toast.ps1` |
| `plugins/marketplaces.json` | Marketplaces to register | consumed by `setup.sh` |
| `plugins/enabled.json` | Plugins to install and enable (must equal the baseline `settings.json`'s `enabledPlugins`; a test pins it) | consumed by `setup.sh` |
| `statusline/ctx-breakdown.py` | ccstatusline widget: colored per-category context chips (system prompt, tools, agents, memory, skills, MCP, messages) | symlink `~/.config/ccstatusline/ctx-breakdown.py` |
| `statusline/session-summary.py` | ccstatusline widget: renders the cached session summary (nothing until the first one lands), word-wrapped across two dim rows on status lines 2-3 (`--row 1` / `--row 2`) | symlink `~/.config/ccstatusline/session-summary.py` |
| `statusline/ccstatusline-settings.json` | ccstatusline layout baseline that wires the ctx-breakdown and session-summary widgets in | installed by `setup.sh` to `~/.config/ccstatusline/settings.json` (paths patched per machine) |
| `tools.json` | Standalone CLI tools (ccstatusline via bun) | consumed by `setup.sh` |
| `docs/PLUGINS.md` | One-line description of each plugin | reference |
| `docs/delegation.md` | Delegation hardening: design, verified facts, known gaps, install order, next stages | reference |
| `docs/prose-is-not-a-permission.md` | Blog post on the delegation work: why a prompt can't limit an agent's authority, and the layers that can | reference |
| `docs/images/` | The post's diagram: `delegation-layers.svg` (source) and `delegation-layers.png` (2x render) | reference |
| `tests/delegation/` | Unit tests for the delegation pieces (no model calls) and `run.py`, a live harness that spends model calls | run from the repo root |
| `tests/setup/` | Unit tests for `merge-settings.py`, `git/install-ignore.py`, and the prompt and session hooks (`handoff_reminder.py`, `session-title.sh`, `session-summary.sh`), the tmux and sound hooks (`test_tmux_hooks.py`), `tmux/tmux-claude-status` (`test_tmux_claude_status.py`) and `setup-tmux.sh`; `replay_history.py` is a local-only replay tool, not a unit test | `python3 -m unittest discover -s tests/setup -t tests/setup` |
| `docs/chrome-devtools-wsl.md` | WSL2-only: how to make `chrome-devtools-mcp` work (Strategy A headless Linux Chrome, plus B to attach to your Windows Chrome) | reference |
| `chrome-debug.ps1` | Windows launcher for Strategy B (Chrome with a remote-debugging port) | run on Windows when needed |
| `tmux/` | The tmux side of the indicator: `claude.conf` (titles, status bar, the ◐ busy and ✳ waiting glyphs), the optional `base.conf` (mouse, splits, the Ctrl-b Enter menu), `cheatsheet.txt`, and `tmux-claude-status`, the backstop the status bar runs (it also maps background sessions to their tab) | sourced and linked by `setup-tmux.sh` |
| `setup-tmux.sh` | Opt-in tmux installer: links `tmux-claude-status` into `~/.local/bin` and keeps a marked `source-file` block in `~/.tmux.conf` (`--base` adds `base.conf` and the cheatsheet) | run once per machine that uses tmux; not called by `setup.sh` |
| `setup-chrome-wsl.sh` | Opt-in WSL2 installer: installs Chrome for Testing and registers the user-scoped `chrome-devtools` override | run once on WSL2; not called by `setup.sh` |
| `setup.sh` | The installer | run once per machine |
| `sync.sh` | Regenerates the derived plugin lists from live `~/.claude/` | run after plugin changes |

## Plugins

`setup.sh` installs eight plugins. Seven are from
[anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official):
`superpowers`, `code-review`, `commit-commands`, `claude-md-management`, `hookify`, `context7`,
`chrome-devtools-mcp`. The eighth, `codex`, comes from the separate `openai-codex` marketplace
([openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc)). See `docs/PLUGINS.md` for
what each does.

`chrome-devtools-mcp` works out of the box on Linux and macOS. On WSL2 it cannot launch Chrome;
run `./setup-chrome-wsl.sh` once to fix it (see `docs/chrome-devtools-wsl.md`). Non-WSL users
need nothing extra.

## Hooks

`settings.json` wires these lifecycle hooks:

- **PreToolUse(`Agent|Task`): `agent-spawn-guard.sh`** (in this repo). Denies a `writer` spawn that
  doesn't pass `isolation` on the Agent call. With agent teams on, a named spawn would otherwise start
  as a teammate in the main checkout, and the writer's frontmatter isolation would be ignored. It also
  denies a named spawn whose name lacks the `team-` prefix (`policy.toml` `[spawn]`), since any
  named spawn silently becomes a teammate.
  **Fails closed**: if the guard script or python3 is missing, it exits 2 and blocks every Agent
  spawn. That is deliberate, but it means `skills/delegation` must be linked before this hook is
  wired (see `docs/delegation.md`, install order). Needs python3 3.11 or newer on PATH (`tomllib`),
  and an unreadable `skills/delegation/policy.toml` denies every spawn too.
- **SubagentStart / SubagentStop: `delegation-ledger.sh`** (in this repo). Appends a pointer row
  (ids, type, paths, whether the final report validated) per delegated agent to
  `${XDG_STATE_HOME:-~/.local/state}/dotclaude/delegations.jsonl`, and keeps a per-agent liveness
  index beside it (`agents/<id>.json`). `delegation-ledger open` lists unfinished delegations
  with the tool each one is in and since when (thresholds in `skills/delegation/liveness.toml`),
  and `delegation-ledger watch` prints one line per live delegation (`--summary` gives a token
  like `2▶ 1⚠` for the tmux bar). The hook never blocks: it always exits 0.
- **PostToolUse(`*`): `delegation-ledger.sh`** (in this repo), for delegated agents only (the
  same `agent_id` prefilter as the policy hook). Once an agent's activation passes its role's
  `nudge_min` (`skills/delegation/policy.toml` `[deadline]`), its next successful call gets one
  reminder to report, as `additionalContext`. Fails open, so a broken install only loses the
  nudge; `subagent-policy` enforces the stop.
- **SessionStart (`startup|resume`): `delegation-due.sh`** (in this repo). Runs
  `delegation-ledger due --hook`: on the first session of a new Claude Code version it starts the
  quick canary in the background (unit tests, sandbox posture, strings in the binary, and a check
  that the installed watch-guard shim runs clean; no model calls), and once a day it starts
  `audit`. It prints one line (a `systemMessage`, for you, not the model) only when a check failed
  or can't run, the daily audit warned, the full `delegation-ledger canary` is due (weekly, when
  the version moved), the monthly `delegation-ledger audit --monthly` is due, a dated item in
  `skills/delegation/due.toml` is due, an unresolved watch's waiter's exit reaches nobody (named
  at every start until it is re-armed or dropped), or a watch ended while no Claude process
  listened (named once). Fails open: always exits 0.
- **PreToolUse(`*`): `subagent-policy.sh`** (in this repo). Runs only for tool calls made inside a
  subagent or teammate (the settings command exits before Python when the input has no
  `agent_id`, so the main thread is never policed). The rules live in
  `skills/delegation/policy.toml`, and `docs/delegation.md` lists them. They include a per-role
  deadline: past `stop_min`, every tool but the handback, SendMessage and ToolSearch is denied.
  **Fails closed** for the tools it polices: a missing link, a crash or a hang blocks the delegated
  call. Needs python3 3.12 or newer.
- **Stop: `watch-guard.sh`** (in this repo), for the main thread. A background Bash command stops
  at its timeout (2 hours at most), and its wake-up note says not to restart it. The guard blocks
  a stop once when a watch from `delegation-ledger wait` (or `codex-delegate`) has lapsed with no
  waiter, or a background command was killed at its time limit, and gives the exact re-arm
  command. After a lapse, the next stop goes through with one warning; a kill or an ended job
  is said once. A plain kill (not a waiter or `codex-delegate`) names no watch: it says how to
  wait with `delegation-ledger wait`. The stop that acknowledges a lapse also starts a detached
  waiter of the guard's own, which watches the whole condition for up to a day; a later stop
  says its end, or its failure. After a `/clear` or a `claude --continue`, the new session's
  first stop adopts the old session's watches: a lapse blocks once more there, and after a
  crash a waiter that still runs blocks once, since its exit reaches nobody. `codex-delegate`
  runs Codex under a detached supervisor, so a killed wrapper leaves Codex running for the
  re-arm, and `codex-delegate cancel` stops a run on purpose. Python's errors go to
  `delegation-ledger.err`, and the quick canary runs the installed shim. `permissions.allow`
  holds `Bash(delegation-ledger wait *)`, so a re-arm never stops at a prompt. Fails open
  (`docs/delegation.md`, "Long waits"). Needs python3 3.11 or newer (it imports `tomllib`
  through `delegation_checks`); with an older one the guard is off, and the error shows in
  `delegation-ledger.err` and the quick canary.
- **PreToolUse(`SubagentHandback`) and SubagentStop: `report-check.sh`** (in this repo). It sends a
  report from `Explore`, `researcher`, `reviewer` or `writer` back when it doesn't match
  `report.schema.json`, at most twice. **Fails open**: a broken checker never swallows a report.
- **UserPromptSubmit: `handoff-reminder.sh`** (in this repo). When a prompt is a genuine session
  wrap-up or context-reset command (`hand off`, `wrap up`, `stop here`, `clear context`, `/clear`),
  it injects a one-line reminder
  to invoke the `handoff` skill rather than improvising its steps (which kept dropping the
  curate-memory step). "handoff" fires the way it's typed in practice, as one action in a list
  ("emailed. handoff", "commit, handoff and push", "deploy handoff and push"), but not in a
  question about it, praise, a delegation ("hand off X to Y") or `/handoff` itself. Generic phrases
  ("wrap up", "stop here", "clear the context") count only as a whole clause, so "don't wrap up
  yet", "clear the session cache" and "stop here, then explain why" stay silent. It also stays
  silent when "handoff" is just a topic (discussing the skill or this hook), on injected content
  (task notifications, subagent and cross-session messages), and on a subagent's or teammate's
  own prompt. Advisory only: it adds context, it cannot run the skill; silent no-op
  otherwise; always exits 0 so it can never block a prompt. The shim runs
  `hooks/handoff_reminder.py` with python3 and stays silent if that fails. After changing it, replay your own typed prompts through it with
  `python3 tests/setup/replay_history.py` (local only: the history holds private names).
- **UserPromptSubmit: `session-title.sh`** (in this repo). Sets the session title (the terminal tab
  title) to `[<repo>] <label>` so tabs are tellable apart. It emits the supported
  `hookSpecificOutput.sessionTitle`, not raw OSC escapes, so the title has display precedence over
  Claude's own AI title and the tab's running/idle status icons stay intact. The repo name comes from
  walking up for `.git` (no git subprocess). The label is chosen by a cascade: the Stop-hook Haiku
  label (`session-summaries/<id>.title.txt`), else the first line of the current prompt, else the
  first clause of the long summary, else the bare `[<repo>]`. (It used to read Claude Code's own
  `ai-title`, but CC 2.1.237 stops generating that once a custom title is set, so the hook was
  suppressing the very record it read; it now owns the label instead.) A subagent's or teammate's
  prompt, or injected content (a task notification, another agent's message), leaves the title as
  it is. Fail-open (exit 0, no output on any error). Needs python3 on PATH.
- **Stop: `session-summary.sh`** (in this repo). On each substantive turn it (re)generates a 1-2
  sentence "what is this session doing, and where does it stand" summary and caches it for the
  status-line widget, so a developer juggling several Claude terminals can re-orient after switching
  back. The same Haiku call also returns a short (`<=32`-char) `LABEL:` line, cached to
  `<id>.title.txt`, that `session-title.sh` uses for the terminal tab title. Generation is a direct
  Haiku Messages-API call authenticated with the Claude subscription
  OAuth token read from `~/.claude/.credentials.json` (stdlib urllib, no API key, no jq), so it burns
  a little 5h/7d subscription quota per turn but skips the system-prompt overhead of a headless
  `claude -p`. Detached so Stop never blocks the turn; fails open (exit 0) on a missing/expired token
  or a failed call, leaving the prior summary in place. A cadence gate skips regeneration when the
  transcript grew < 2KB, and the prior summary is fed back in. Task notifications, agent messages
  and skill bodies are left out of the dialogue it sends, so they aren't summarized as the user's
  request. Needs python3 on PATH.
- **Stop / Notification sounds**: play a Windows sound and (on permission prompts) a toast. Both
  sounds ring only for a session a person sees: a tab, a plain terminal, or a background session
  mapped to its tab (see the tmux indicator). Subagents, unmapped background sessions and
  `claude -p` runs (the delegation canary is one) stay quiet; a permission prompt still pops the
  toast, so a stuck background session shows up. `hooks/session-pane.sh`'s header
  has the rules and the hook env they read. Each decision is a line in
  `$XDG_STATE_HOME/dotclaude/ring.log`. The toast goes through `notify.sh`, which resolves the path
  for both WSL (`wslpath`) and native Windows git-bash (`cygpath`) and renders `notify-toast.ps1`;
  Windows' Do Not Disturb hides it. Windows-only: on macOS/Linux, swap for your platform's notifier
  (`osascript` / `notify-send`).
- **tmux indicator**: `tmux-state.sh` marks the session's window busy (◐) on a prompt or tool
  call, waiting (✳) on a Notification and idle on Stop. `claude -p` runs never set it. A
  background session has no pane of its own, so `tmux/tmux-claude-status` maps it by directory to
  the one client pane in its cwd (two background sessions in one directory map nothing, and a new
  mapping also needs a single client pane there) and writes
  `$XDG_STATE_HOME/dotclaude/tabs`, which `session-pane.sh` reads. State is per window, so two
  sessions split into one window share a glyph.
  Run `./setup-tmux.sh` once for the tmux side. A machine whose `settings.machine.json` still wires
  `tmux-state.sh` should drop those entries before `./setup.sh`, or they fire twice.

## Status line

`settings.json` runs [ccstatusline](https://github.com/sirmalloc/ccstatusline) at
`$HOME/.bun/bin/ccstatusline`. `setup.sh` installs it from `tools.json` with
`bun install -g ccstatusline`. If bun is not on PATH the status line is blank but Claude Code
works fine.

`statusline/ctx-breakdown.py` adds a custom widget that splits context usage into colored
chips by category: system prompt, system tools, custom agents, memory, skills, MCP, and
messages. Claude Code only exposes lump token totals to statusline scripts, so the widget
parses the fixed-overhead categories from the most recent `/context` output stored in the
session transcript, and computes the messages figure live (total minus overhead) from the
totals piped on stdin. Run `/context` once per session to seed the split; until then the
widget shows the total with a hint. The total chip shows the token count and its percent
of the window, set off from the per-category chips by a thin divider; it is green, turns
amber past 50% of the context window, red past 66%, and blinking bright red past 83%
(about 400k and 500k of a 600k window; terminals without blink support show it static).
`statusline/session-summary.py` adds a second custom widget on status lines 2 and 3 (previously
empty): a 1-2 sentence plain-language summary of what the session is doing and where it stands,
word-wrapped to the terminal width across two dim rows (`--row 1` / `--row 2`). The text is produced
out-of-band by the `session-summary.sh` Stop hook and cached per session; the widget only reads that
cache, so a fresh session shows nothing here until the first summary lands. Line 1 (model,
context, git, usage) is left untouched so anything that keys on it keeps working.

Both widgets live in ccstatusline's config dir, so reinstalling or upgrading ccstatusline
never touches them.

## What's deliberately not here

- **Secrets**: `~/.claude/.credentials.json`, MCP auth tokens. Re-auth per machine.
- **Plugin content**: plugin-shipped skills, commands, and hooks. Installed from their
  marketplaces.
- **Local state**: `history.jsonl`, `projects/`, memory entries, `sessions/`, caches, logs.
  Runtime artifacts, not configuration (see `.gitignore`).

## License

MIT for the configuration and scripts in this repo. Plugin licenses are governed by their
upstream projects.
