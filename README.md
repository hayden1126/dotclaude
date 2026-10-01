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
it drops; put a value in the overlay to keep it.

## What's in here

| Path | What it is | Installs to |
|---|---|---|
| `CLAUDE.md` | Global instructions: working partnership, boundaries, voice, the explore -> spec -> plan -> execute -> verify -> review workflow | symlink `~/.claude/CLAUDE.md` |
| `settings.json` | Hooks, status line, env vars, enabled plugins, and the Bash sandbox (curated baseline; see docs/delegation.md for the sandbox) | **copy** to `~/.claude/settings.json` (runtime-managed, not symlinked), merged with `~/.claude/settings.machine.json` when present |
| `merge-settings.py` | Merges the machine overlay into the baseline and keeps the live file's own top-level keys, for `setup.sh` | run by `setup.sh` |
| `git/sandbox-stubs.ignore` | Git ignore patterns for the `/dev/null` mounts the Bash sandbox puts over protected dotfiles a repo lacks (they break `git add -A`) | upserted by `git/install-ignore.py` between markers in the global git excludes file (`core.excludesFile`, else `~/.config/git/ignore`); Linux only |
| `skills/` | The skills I authored: `coding-practices`, `research-discipline`, `research-sourcing`, `writing-voice`, `staged-reader-review`, `ebook-extract`, `deck-production`, `vetting-sources`, `handoff`, `frontend-ui-discipline`, `ui-alignment`, `delegation` | symlink per dir into `~/.claude/skills/`; a skill's `scripts/` CLI also symlinks into `~/.local/bin` when that dir exists (`deck-production` ships `deckkit`; `delegation` ships `codex-delegate`, `delegation-ledger` and `gh-public`) |
| `agents/` | Delegation roles: `Explore` (overrides the built-in with a no-shell reader), `researcher`, `reviewer`, `writer`; see docs/delegation.md | symlink per file into `~/.claude/agents/` |
| `hooks/agent-spawn-guard.sh` | PreToolUse(Agent) guard: denies a `writer` spawn that doesn't pass `isolation` on the call, and a named spawn without the `team-` prefix; fails closed | symlink `~/.claude/hooks/agent-spawn-guard.sh` |
| `hooks/delegation-ledger.sh` | SubagentStart/SubagentStop hook: appends a pointer row per delegated agent to the delegation ledger; never blocks | symlink `~/.claude/hooks/delegation-ledger.sh` |
| `hooks/delegation-due.sh` | SessionStart hook: runs the cheap delegation checks in the background (the quick canary on a new Claude Code version, a daily audit) and shows a line only when something is due; fails open | symlink `~/.claude/hooks/delegation-due.sh` |
| `hooks/subagent-policy.sh` | PreToolUse(*) policy for delegated agents only (rules in `skills/delegation/policy.toml`): no leaving the sandbox, no destructive git, no MCP writes, protected paths, the researcher allowlist, writers held to their worktree; fails closed | symlink `~/.claude/hooks/subagent-policy.sh` |
| `hooks/report-check.sh` | PreToolUse(SubagentHandback)/SubagentStop hook: sends a delegated role's malformed report back, at most twice; fails open | symlink `~/.claude/hooks/report-check.sh` |
| `hooks/danger-guard.sh` | PreToolUse(Bash) guard: two-tier confirmation for destructive git and `rm` ops | symlink `~/.claude/hooks/danger-guard.sh` |
| `hooks/handoff-reminder.sh` | UserPromptSubmit hook: on a wrap-up / handoff / clear-memory signal, reminds me to invoke the `handoff` skill instead of improvising it | symlink `~/.claude/hooks/handoff-reminder.sh` |
| `hooks/session-title.sh` | UserPromptSubmit hook: sets the terminal tab title to `[<repo>] <label>` via `sessionTitle`, so tabs are tellable apart; the label comes from the Stop-hook Haiku cache (`.title.txt`), falling back to the current prompt's first line | symlink `~/.claude/hooks/session-title.sh` |
| `hooks/stop-ring.sh` | Stop hook: plays the Windows notify sound when the main session finishes, not when a subagent or background agent stops | symlink `~/.claude/hooks/stop-ring.sh` |
| `hooks/notify.sh` | Notification(permission_prompt) hook: pops a Windows toast, resolving the toast path per platform (WSL via `wslpath`, native Windows git-bash via `cygpath`) | symlink `~/.claude/hooks/notify.sh` |
| `hooks/session-summary.sh` | Stop hook: regenerates a 1-2 sentence session summary via a direct Haiku Messages-API call (Claude subscription OAuth token, stdlib urllib, no API key/jq), detached so it never blocks; caches the summary to `<config-dir>/session-summaries/<session_id>.txt` for the status-line widget and a short (`<=32`-char) tab label to `<session_id>.title.txt` for `session-title.sh` | symlink `~/.claude/hooks/session-summary.sh` |
| `templates/` | `SPEC.md`, `PLAN.md`, `STATUS.md` scaffolds for full-lane work that survive `/clear` | symlink per file into `~/.claude/templates/` |
| `codex/` | Codex CLI config (config.toml baseline + AGENTS.md + merge-config.py); see docs/codex.md | symlink `AGENTS.md` into `~/.codex/`; merge `config.toml`'s keys into the local `~/.codex/config.toml` (Codex writes to it, so it is never linked; `auth.json` stays local) |
| `notify-toast.ps1` | Windows toast script that `notify.sh` renders for the Notification hook | symlink `~/.claude/notify-toast.ps1` |
| `plugins/marketplaces.json` | Marketplaces to register | consumed by `setup.sh` |
| `plugins/enabled.json` | Plugins to install and enable | consumed by `setup.sh` |
| `statusline/ctx-breakdown.py` | ccstatusline widget: colored per-category context chips (system prompt, tools, agents, memory, skills, MCP, messages) | symlink `~/.config/ccstatusline/ctx-breakdown.py` |
| `statusline/session-summary.py` | ccstatusline widget: renders the cached session summary (falls back to the transcript ai-title, now usually absent since CC 2.1.237), word-wrapped across two dim rows on status lines 2-3 (`--row 1` / `--row 2`) | symlink `~/.config/ccstatusline/session-summary.py` |
| `statusline/ccstatusline-settings.json` | ccstatusline layout baseline that wires the ctx-breakdown and session-summary widgets in | installed by `setup.sh` to `~/.config/ccstatusline/settings.json` (paths patched per machine) |
| `tools.json` | Standalone CLI tools (ccstatusline via bun) | consumed by `setup.sh` |
| `docs/PLUGINS.md` | One-line description of each plugin | reference |
| `docs/delegation.md` | Delegation hardening: design, verified facts, known gaps, install order, next stages | reference |
| `tests/delegation/` | Unit tests for the delegation pieces (no model calls) and `run.py`, a live harness that spends model calls | run from the repo root |
| `tests/setup/` | Unit tests for `merge-settings.py` and `git/install-ignore.py` | `python3 -m unittest discover -s tests/setup -t tests/setup` |
| `docs/chrome-devtools-wsl.md` | WSL2-only: how to make `chrome-devtools-mcp` work (Strategy A headless Linux Chrome, plus B to attach to your Windows Chrome) | reference |
| `chrome-debug.ps1` | Windows launcher for Strategy B (Chrome with a remote-debugging port) | run on Windows when needed |
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

`settings.json` wires these lifecycle hooks (all run by default except `danger-guard`, which
ships but is opt-in, see its entry):

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
  like `2▶ 1⚠` for the tmux bar). The hook is an observer only: it prints nothing and always
  exits 0.
- **SessionStart (`startup|resume`): `delegation-due.sh`** (in this repo). Runs
  `delegation-ledger due --hook`: on the first session of a new Claude Code version it starts the
  quick canary in the background (unit tests, sandbox posture, strings in the binary; no model
  calls), and once a day it starts `audit`. It prints one line (a `systemMessage`, for you, not the
  model) only when a check failed or can't run, the daily audit warned, the full
  `delegation-ledger canary` is due (weekly, when the version moved), or a dated item in
  `skills/delegation/due.toml` is due. Fails open: always exits 0.
- **PreToolUse(`*`): `subagent-policy.sh`** (in this repo). Runs only for tool calls made inside a
  subagent or teammate (the settings command exits before Python when the input has no
  `agent_id`, so the main thread is never policed). The rules live in
  `skills/delegation/policy.toml`, and `docs/delegation.md` lists them.
  **Fails closed** for the tools it polices: a missing link, a crash or a hang blocks the delegated
  call. Needs python3 3.12 or newer.
- **PreToolUse(`SubagentHandback`) and SubagentStop: `report-check.sh`** (in this repo). It sends a
  report from `Explore`, `researcher`, `reviewer` or `writer` back when it doesn't match
  `report.schema.json`, at most twice. **Fails open**: a broken checker never swallows a report.
- **UserPromptSubmit: `handoff-reminder.sh`** (in this repo). When a prompt is a genuine session
  wrap-up or context-reset command (`hand off`, `wrap up`, `stop here`, `clear context`, `/clear`),
  it injects a one-line reminder
  to invoke the `handoff` skill rather than improvising its steps (which kept dropping the
  curate-memory step). Precision-first: it stays silent when "handoff" is just a topic (discussing
  the skill or this hook) and on injected system content (task notifications). Advisory only: it adds context, it cannot run the skill; silent no-op
  otherwise; always exits 0 so it can never block a prompt. Fail-open if `jq` is absent.
- **UserPromptSubmit: `session-title.sh`** (in this repo). Sets the session title (the terminal tab
  title) to `[<repo>] <label>` so tabs are tellable apart. It emits the supported
  `hookSpecificOutput.sessionTitle`, not raw OSC escapes, so the title has display precedence over
  Claude's own AI title and the tab's running/idle status icons stay intact. The repo name comes from
  walking up for `.git` (no git subprocess). The label is chosen by a cascade: the Stop-hook Haiku
  label (`session-summaries/<id>.title.txt`), else the first line of the current prompt, else the
  first clause of the long summary, else the bare `[<repo>]`. (It used to read Claude Code's own
  `ai-title`, but CC 2.1.237 stops generating that once a custom title is set, so the hook was
  suppressing the very record it read; it now owns the label instead.) Fail-open (exit 0, no output
  on any error). Needs python3 on PATH.
- **PreToolUse(Bash): `danger-guard.sh`** (in this repo, **ships but not wired by default**).
  The script is symlinked into `~/.claude/hooks/` so it is ready to use, but `settings.json`
  intentionally carries no `PreToolUse` entry for `Bash` (dropped in `8602081`: `setup.sh` would
  otherwise silently re-enable a guard some machines want off). Opt in by adding a `Bash` matcher that
  runs it to the existing `PreToolUse` array. Once wired it works in two tiers: it hard-blocks
  (`deny`) never-legitimate ops (force-push, `reset --hard`, `git clean -f`) and prompts
  (`ask`) for routine-but-sensitive ops (plain push, checkout, switch, revert, `rm -rf`).
  Token-aware, so it does not trip on `git commit -m "push fix"`, and it recurses into
  `bash -c "..."` and `eval` wrappers. Fires for the main agent and all subagents. Fail-open
  on any parse error. Needs python3 on PATH.
  An optional **auto mode** flips the guard to allow-by-default: every dangerous op (both
  tiers) is downgraded to a single `ask` prompt and every other bash command is auto-approved
  (`allow`). So force-push still needs an explicit yes, but nothing is hard-blocked and routine
  commands stop prompting. Toggle it live with `touch ~/.claude/.danger-guard-auto` (`rm` to
  disable), or at launch with `DANGER_GUARD_AUTO=1 claude`.
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
  transcript grew < 2KB, and the prior summary is fed back in. Needs python3 on PATH.
- **Stop / Notification sounds**: play a Windows sound and (on permission prompts) a toast. The
  Notification sound is inline in `settings.json`. The Stop sound is `stop-ring.sh`, which rings only
  when the main session finishes: Stop also fires for every subagent and background agent, and those
  carry `agent_id`. The toast goes through `notify.sh`, which resolves the path for both WSL (`wslpath`) and
  native Windows git-bash (`cygpath`) and renders `notify-toast.ps1`. Windows-only: on macOS/Linux,
  swap for your platform's notifier (`osascript` / `notify-send`).

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
cache, falling back to Claude Code's own ai-title before the first summary lands (now usually absent
since CC 2.1.237, so a fresh session may show nothing here until the first summary). Line 1 (model,
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
