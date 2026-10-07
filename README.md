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

The baseline's `permissions` deny destructive git and ask before anything that can reach `main`,
in auto mode too. Denied: force-push, `reset --hard`, `reset --merge` and `git clean -f`, plain or
through `git -C`, plus a `bash -c` whose text has `git push` then `--force`, or `git reset` then
`--hard`. Asked: a push whose text has `main`, `HEAD`, `@`, `--all` or `--mirror`, one that names
no branch (`git push`, `git push origin`), one starting with a flag (`git push -u ...`,
`git push origin --no-verify`), a `+` force the deny rules miss, any `git -C <dir> push`, and
merges (`gh pr merge`, `gh api ...merge`). Allowed without a prompt: `git push origin <branch>`
and `gh pr create`; CLAUDE.md still has Claude ask in words first. Also allowed, because the
classifier once refused a CI watch with no reason given: the read-only `gh pr checks`, `view`,
`list`, `status` and `diff`, and `gh run list`, `view` and `watch`. Read-only git (`status`,
`log`, `diff`, `show`, `rev-parse`; the classifier once refused one as an "unrequested commit")
is allowed too, with the pipe filters `head`, `tail`, `wc` and `grep`, since every part of a pipe
needs its own rule. `git ... --output` writes a file, so it asks. A `cd <dir> && git ...` still
goes to the classifier, even with a `Bash(cd *)` rule: Claude Code sends `cd` plus `git` there
whatever the rules say. `git -C <dir> status` and the other `-C` reads go there too, since a
`git -C * log*` rule would also match a commit. A rule can't see the current branch, which is
why every form that could land on `main` without naming it asks. Not checked (accepted): flags
after the branch, remotes other than `origin`, and deleting a branch other than `main` with
`origin :branch` (no rule can match ` :` without a `:*`, which Claude Code reads as its legacy
prefix form or warns about at every start). Everything else goes to auto mode's classifier: other
wrappers (any other `bash -c`, such as one running `push -f`, and `bash -lc`, `sh -c`, `eval`),
git global options other than `-C` (`-c k=v`, `--git-dir`, `--no-pager`), soft, mixed and
`--keep` resets, and `checkout`, `switch`, `restore` and `revert`. Why rules at all: on 2.1.288,
auto mode ran a force-push and a `reset --hard` on a dirty tree when the prompt named them.

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
later word, such as `git -C <dir> stash push`, and a push to a branch whose name contains `main`,
`HEAD`, `@` or `+`. Permission rules apply to delegated agents as well,
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
| `hooks/stop-ring.sh` | Stop hook: plays the Windows notify sound when a session you see finishes (a tab, a plain terminal or a mapped background session), not a subagent, an unmapped background session, a `claude -p` run, a turn that ends with an agent or shell still running for it, or one a queued notice or prompt restarts within a second; logs each decision to `ring.log` | symlink `~/.claude/hooks/stop-ring.sh` |
| `hooks/notify.sh` | Notification(permission_prompt) hook: pops a Windows toast, resolving the toast path per platform (WSL via `wslpath`, native Windows git-bash via `cygpath`), and rings like `stop-ring.sh` | symlink `~/.claude/hooks/notify.sh` |
| `hooks/tmux-state.sh` | Prompt, tool, Stop and Notification hook: sets `@claude_state` (busy, wait, idle) on the tmux window the session is shown in, for the indicator in `tmux/claude.conf`; does nothing outside tmux | symlink `~/.claude/hooks/tmux-state.sh` |
| `hooks/session-pane.sh` | Sourced by the three hooks above, not a hook: finds the tmux pane a session is shown in, and whether a person sees it | symlink `~/.claude/hooks/session-pane.sh` |
| `hooks/session-registry.sh` | SessionStart/SessionEnd hook: records which session is open in which tmux tab (`$XDG_STATE_HOME/dotclaude/open-sessions/`), for `claude-restore`; deletes the entry on `/exit` or `/clear`, marks it when the window or claude is killed; does nothing outside tmux | symlink `~/.claude/hooks/session-registry.sh` |
| `hooks/session-summary.sh` | Stop hook: regenerates a 1-2 sentence session summary via a direct Haiku Messages-API call (Claude subscription OAuth token, stdlib urllib, no API key/jq), detached so it never blocks; caches the summary to `<config-dir>/session-summaries/<session_id>.txt` for the status-line widget and a short (`<=32`-char) tab label to `<session_id>.title.txt` for `session-title.sh` | symlink `~/.claude/hooks/session-summary.sh` |
| `hooks/overwrite-guard.sh` | PreToolUse(Write) hook: denies a Write over a file this session hasn't read, or one that cuts a file of 1 KB or more to under a fifth; a shim over `hooks/overwrite_guard.py`; fails open | symlink `~/.claude/hooks/overwrite-guard.sh` and `overwrite_guard.py` |
| `hooks/delete-guard.sh` | PreToolUse(Bash) hook, sandbox-off commands only: denies a delete whose path uses a variable the command didn't set, a command substitution that would widen it if empty, or a top-level or home tree; a shim over `hooks/delete_guard.py`; fails open | symlink `~/.claude/hooks/delete-guard.sh` and `delete_guard.py` |
| `hooks/memory-git.sh` | SessionStart/Stop hook: commits every project's auto-memory to a local-only git repo (`$XDG_STATE_HOME/dotclaude/memory.git`); never blocks | symlink `~/.claude/hooks/memory-git.sh` |
| `bin/claude-file-history` | Lists and restores Claude Code's own backups of a file (`~/.claude/file-history`), found through the transcripts | symlink `~/.local/bin/claude-file-history` when that dir exists |
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
| `tests/setup/` | Unit tests for `merge-settings.py`, `git/install-ignore.py`, and the prompt and session hooks (`handoff_reminder.py`, `session-title.sh`, `session-summary.sh`), the tmux and sound hooks (`test_tmux_hooks.py`), `tmux/tmux-claude-status` (`test_tmux_claude_status.py`), the restore after tmux dies (`test_session_registry.py`, `test_claude_restore.py`), `setup-tmux.sh`, the overwrite and delete guards, `memory-git.sh` and `claude-file-history`; `replay_history.py` is a local-only replay tool, not a unit test | `python3 -m unittest discover -s tests/setup -t tests/setup` |
| `tests/deck_production/` | Unit tests for `deck-production`'s `deckkit geometry` gate (rule matrix on canned probe output, plus an end-to-end run over the synthetic `fixtures/geodeck` that skips without a headless Chrome) `deckkit regress`'s geometry facts, and `deckkit doctor`'s exit codes | `python3 -m unittest discover -s tests/deck_production -t tests/deck_production` |
| `docs/blind-overwrite-brief.md` | Why the overwrite guard and `memory-git.sh` exist: two incidents (a blind overwrite of a memory file, a job's state inferred instead of read), the experiments and the design calls | reference |
| `docs/chrome-devtools-wsl.md` | WSL2-only: how to make `chrome-devtools-mcp` work (Strategy A headless Linux Chrome, plus B to attach to your Windows Chrome) | reference |
| `chrome-debug.ps1` | Windows launcher for Strategy B (Chrome with a remote-debugging port) | run on Windows when needed |
| `tmux/` | The tmux side of the indicator: `claude.conf` (titles, status bar, the ◐ busy and ✳ waiting glyphs), the optional `base.conf` (mouse, splits, the Ctrl-b Enter menu), `cheatsheet.txt`, `tmux-claude-status`, the backstop the status bar runs (it also maps background sessions to their tab), and `claude-restore`, which reopens `main`'s Claude tabs after the tmux server dies | sourced and linked by `setup-tmux.sh` |
| `setup-tmux.sh` | Opt-in tmux installer: links `tmux-claude-status` and `claude-restore` into `~/.local/bin` and keeps a marked `source-file` block in `~/.tmux.conf` (`--base` adds `base.conf` and the cheatsheet) | run once per machine that uses tmux; not called by `setup.sh` |
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
  `claude -p` runs (the delegation canary is one) stay quiet, and so does a Stop while an agent or
  shell it started is still running (`ring.log` marks it `quiet busy=1`). A ring waits a second
  and is dropped if a queued input (a task notice that landed mid-turn, a prompt typed mid-turn)
  starts the next turn at once (`quiet resumed=1`); a permission prompt still pops the
  toast, so a stuck background session shows up. `hooks/session-pane.sh`'s header
  has the rules and the hook env they read. Each decision is a line in
  `$XDG_STATE_HOME/dotclaude/ring.log`. The toast goes through `notify.sh`, which resolves the path
  for both WSL (`wslpath`) and native Windows git-bash (`cygpath`) and renders `notify-toast.ps1`;
  Windows' Do Not Disturb hides it. Windows-only: on macOS/Linux, swap for your platform's notifier
  (`osascript` / `notify-send`).
- **tmux indicator**: `tmux-state.sh` marks the session's window busy (◐) on a prompt or tool
  call, waiting (✳) on a permission prompt or a question (not `idle_prompt`) and idle on Stop; a background subagent's tool calls leave
  a waiting window alone. `claude -p` runs never set it. A
  background session has no pane of its own, so `tmux/tmux-claude-status` maps it by directory to
  the one client pane in its cwd (two background sessions in one directory map nothing, and a new
  mapping also needs a single client pane there) and writes
  `$XDG_STATE_HOME/dotclaude/tabs`, which `session-pane.sh` reads. State is per window, so two
  sessions split into one window share a glyph.
  Run `./setup-tmux.sh` once for the tmux side. A machine whose `settings.machine.json` still wires
  `tmux-state.sh` should drop those entries before `./setup.sh`, or they fire twice.
- **Tabs come back after tmux dies**: a Windows restart, `wsl --shutdown`, `wsl --terminate` or
  `tmux kill-server` ends the tmux server and every Claude tab in `main`. `session-registry.sh`
  keeps one file per open tab in `$XDG_STATE_HOME/dotclaude/open-sessions/`: the session id, its
  directory, transcript, pane, window index, and the tmux server it runs under (socket path,
  start time and pid). `/exit` and `/clear` delete the old id's file (a `/clear`d tab is recorded again
  under its new id). Killing the window, claude or the tmux server only marks it, since a
  shutdown that signals claude looks the same to a hook. When `main` is next created, tmux's
  `session-created` hook runs `claude-restore --auto main`. It takes the files from the same
  socket but an earlier server (other sockets, like a `tmux -L` test server, are left alone) and opens one window per tab, in the old order, running `claude --resume <id>` in its
  directory. A marked tab comes back only if it ended within 120 s of its own server's
  last activity (the shutdown itself); one closed earlier stays closed. It skips a session
  already running, a deleted directory, and an older session in the same pane (one claude runs
  in a pane at a time, so only the newest can be a live tab). A directory name with a `#` is
  skipped (tmux would expand it), and so is one with a control character. A tab with no transcript yet (fresh from startup or `/clear`: a
  session writes none until its first input) reopens as a plain `claude` in its directory.
  `claude-restore --list` shows what it would do and why; `claude-restore` with no flag restores
  now. If tmux fails to open a window, the entry stays for the next run. Each decision is a line in `$XDG_STATE_HOME/dotclaude/restore.log`, and
  the last restore's files stay in `open-sessions/restored/`. Known limit: a window killed just
  before tmux dies with nothing else running is in that final 120 s, so it comes back. An
  extra tab is cheap; losing every tab is what this exists to prevent. Background (`--bg`)
  sessions are not restored.
- **PreToolUse(`Write`): `overwrite-guard.sh`** (in this repo). The Write tool's own "File has not
  been read yet" check last fired in Claude Code 2.1.285, and on 2.1.289 a Write of `PLACEHOLDER`
  replaced an unread 6 KB memory file (`docs/blind-overwrite-brief.md`). The guard denies a Write
  over an existing, non-empty file in two cases:
  - this session's transcript shows no successful Read, Write, Edit, MultiEdit or NotebookEdit of
    that path, no successful Bash command naming its path, no @-mention of it, and no loaded
    instructions file at that path (*read-proof*);
  - the Write would cut a file of 1 KB or more to under a fifth of its size, even after a Read
    (*shrink*).

  A Bash command counts when it names the file's path (absolute, `~/`, or relative to the cwd it ran
  in), so `cat README.md` in one repo proves nothing about another repo's README.md. A subagent is
  judged by its own transcript. Replayed over 292 real overwrites, the guard would have denied 17
  (16 read-proof, 1 shrink), the incident among them. Each deny costs one Read. Fails open: an
  error allows the Write, and a transcript it can't find skips read-proof (shrink still applies).
  Errors and denies are logged to `$XDG_STATE_HOME/dotclaude/overwrite-guard.log`.
- **PreToolUse(`Bash`): `delete-guard.sh`** (in this repo), for commands run with
  `dangerouslyDisableSandbox` only (the settings command skips Python for every other call).
  Inside the sandbox a delete reaches only the working directory and `$TMPDIR`; outside it reaches
  everything, and `$TMPDIR` is plain `/tmp`, which once aimed an `rm -rf "$TMPDIR"/...` at shared
  `/tmp`. The guard denies a delete (`rm`, `rmdir`, `shred`, `unlink`, `find -delete` or
  `-exec rm`) when a path:
  - uses a variable the command didn't set before it (other than `HOME` and `USER`), a
    positional parameter nothing set, or a variable built from one (`D="$TMPDIR/x"`);
  - uses an operator expansion (`${X:-/tmp}`), or a command substitution that would widen the
    path if it came back empty (`"$(mktemp -d)"/*` becomes `/*`; a lone `"$dir"` is fine);
  - is a top-level or home tree, or a glob directly inside one (`/`, `/tmp/*`, `~`, `~/.*`,
    `~/{code,vault}`, `~/.claude`, ...), following the command's own values, `for` loops and
    `set --`;
  - is relative, after a `cd` into an untrusted path or a top-level tree (`cd "$TMPDIR" && rm -rf ./*`).

  Ordinary cleanup passes: a narrower glob (`rm -rf /tmp/pytest-*`), `"${dir:?}"/*`, and a
  `find` that filters what it deletes (`find ~/code -name __pycache__ -exec rm -rf {} +`).

  Replayed over a month of transcripts (4367 sandbox-off calls), it would have denied 6, every one
  a path built from `$TMPDIR` where it was `/tmp`. Normal `rm` never asks. Not covered:
  `xargs rm`, a delete inside `bash -c`, `eval`, a function or a script, and a glob two levels
  down (`~/*/*`). Fails open; denies go to
  `$XDG_STATE_HOME/dotclaude/delete-guard.log`.
- **SessionStart / Stop: `memory-git.sh`** (in this repo). Commits every project's auto-memory
  (`~/.claude/projects/*/memory/`) to a local-only git repo at
  `$XDG_STATE_HOME/dotclaude/memory.git`, so a memory file broken by any means, a Bash heredoc
  included, can be restored. Transcripts are never tracked, and the repo has no remote. A
  session that finds another one mid-commit skips, and the next trigger commits. Never blocks.

**A file got overwritten?** Claude Code backs up a file before each tool write, outside the
working directory too, for as long as the session's transcript is kept (about 30 days). Bash
writes are not covered.
- `claude-file-history <path>` lists every backup across sessions. `--show N` prints one, and
  `--restore N` puts one back after saving the current file beside it.
- For memory, `git --git-dir="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude/memory.git" log
  --stat` goes back further and covers Bash edits.

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
