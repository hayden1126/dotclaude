# My Claude Code setup

A portable snapshot of my global [Claude Code](https://docs.claude.com/en/docs/claude-code/overview)
configuration: global instructions, the skills and hooks Hayden and Friends authored, durable-state templates,
settings, and the plugins I install. Run `./setup.sh` on a fresh machine and end up with the
same setup.

This is a deliberately lean, principle-driven config. It vendors only what Hayden and Friends wrote or curated.
Plugin-owned content (plugin skills, agents, hooks) is installed from the plugins' own
marketplaces, not copied here, so it never goes stale.

## Quickstart

```bash
git clone https://github.com/hayden1126/dotclaude.git
cd dotclaude
./setup.sh
claude login        # one-time auth
```

`setup.sh` is idempotent. Existing real files in `~/.claude/` are backed up to
`~/.claude/backups/pre-dotclaude-<timestamp>/`, then replaced with symlinks back to this repo,
so edits in either place stay in sync. The one exception is `settings.json`: it is **copied**, not
symlinked, because the Claude Code runtime rewrites it (persisting managed keys like
`extraKnownMarketplaces`). A symlink would push that churn back into the repo; the copy keeps the
repo file as a curated baseline while the runtime owns its own copy.

## What's in here

| Path | What it is | Installs to |
|---|---|---|
| `CLAUDE.md` | Global instructions: working partnership, boundaries, voice, the explore -> spec -> plan -> execute -> verify -> review workflow | symlink `~/.claude/CLAUDE.md` |
| `settings.json` | Hooks, status line, env vars, enabled plugins (curated baseline) | **copy** to `~/.claude/settings.json` (runtime-managed, not symlinked) |
| `skills/` | The skills I authored: `coding-practices`, `research-discipline`, `research-sourcing`, `writing-voice`, `staged-reader-review`, `ebook-extract`, `handoff` | symlink per dir into `~/.claude/skills/` |
| `hooks/danger-guard.sh` | PreToolUse(Bash) guard: two-tier confirmation for destructive git and `rm` ops | symlink `~/.claude/hooks/danger-guard.sh` |
| `hooks/handoff-reminder.sh` | UserPromptSubmit hook: on a wrap-up / handoff / clear-memory signal, reminds me to invoke the `handoff` skill instead of improvising it | symlink `~/.claude/hooks/handoff-reminder.sh` |
| `hooks/notify.sh` | Notification(permission_prompt) hook: pops a Windows toast, resolving the toast path per platform (WSL via `wslpath`, native Windows git-bash via `cygpath`) | symlink `~/.claude/hooks/notify.sh` |
| `templates/` | `SPEC.md`, `PLAN.md`, `STATUS.md` scaffolds for full-lane work that survive `/clear` | symlink per file into `~/.claude/templates/` |
| `notify-toast.ps1` | Windows toast script that `notify.sh` renders for the Notification hook | symlink `~/.claude/notify-toast.ps1` |
| `plugins/marketplaces.json` | Marketplaces to register | consumed by `setup.sh` |
| `plugins/enabled.json` | Plugins to install and enable | consumed by `setup.sh` |
| `statusline/ctx-breakdown.py` | ccstatusline widget: colored per-category context chips (system prompt, tools, agents, memory, skills, MCP, messages) | symlink `~/.config/ccstatusline/ctx-breakdown.py` |
| `statusline/ccstatusline-settings.json` | ccstatusline layout baseline that wires the widget in | installed by `setup.sh` to `~/.config/ccstatusline/settings.json` (paths patched per machine) |
| `tools.json` | Standalone CLI tools (ccstatusline via bun) | consumed by `setup.sh` |
| `docs/PLUGINS.md` | One-line description of each plugin | reference |
| `docs/chrome-devtools-wsl.md` | WSL2-only: how to make `chrome-devtools-mcp` work (Strategy A headless Linux Chrome, plus B to attach to your Windows Chrome) | reference |
| `chrome-debug.ps1` | Windows launcher for Strategy B (Chrome with a remote-debugging port) | run on Windows when needed |
| `setup-chrome-wsl.sh` | Opt-in WSL2 installer: installs Chrome for Testing and registers the user-scoped `chrome-devtools` override | run once on WSL2; not called by `setup.sh` |
| `setup.sh` | The installer | run once per machine |
| `sync.sh` | Regenerates the derived plugin lists from live `~/.claude/` | run after plugin changes |

## Plugins

`setup.sh` installs seven plugins, all from
[anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official):
`superpowers`, `code-review`, `commit-commands`, `claude-md-management`, `hookify`, `context7`,
`chrome-devtools-mcp`. See `docs/PLUGINS.md` for what each does.

`chrome-devtools-mcp` works out of the box on Linux and macOS. On WSL2 it cannot launch Chrome;
run `./setup-chrome-wsl.sh` once to fix it (see `docs/chrome-devtools-wsl.md`). Non-WSL users
need nothing extra.

## Hooks

`settings.json` wires four lifecycle hooks:

- **UserPromptSubmit: `handoff-reminder.sh`** (in this repo). When a prompt is a genuine session
  wrap-up or context-reset command (`hand off`, `wrap up`, `stop here`, `clear context`, `/clear`),
  it injects a one-line reminder
  to invoke the `handoff` skill rather than improvising its steps (which kept dropping the
  curate-memory step). Precision-first: it stays silent when "handoff" is just a topic (discussing
  the skill or this hook) and on injected system content (task notifications). Advisory only: it adds context, it cannot run the skill; silent no-op
  otherwise; always exits 0 so it can never block a prompt. Fail-open if `jq` is absent.
- **PreToolUse(Bash): `danger-guard.sh`** (in this repo). Two tiers. It hard-blocks
  (`deny`) never-legitimate ops (force-push, `reset --hard`, `git clean -f`) and prompts
  (`ask`) for routine-but-sensitive ops (plain push, checkout, switch, revert, `rm -rf`).
  Token-aware, so it does not trip on `git commit -m "push fix"`, and it recurses into
  `bash -c "..."` and `eval` wrappers. Fires for the main agent and all subagents. Fail-open
  on any parse error. Needs python3 on PATH.
  An optional **auto mode** flips the guard to allow-by-default: every dangerous op (both
  tiers) is downgraded to a single `ask` prompt and every other bash command is auto-approved
  (`allow`). So force-push still needs an explicit yes, but nothing is hard-blocked and routine
  commands stop prompting. Toggle it live with `touch ~/.claude/.danger-guard-auto` (`rm` to
  disable), or at launch with `DANGER_GUARD_AUTO=1 claude`. Off by default.
- **Stop** and **Notification**: play a Windows sound and (on permission prompts) a toast. The
  sound hooks are inline in `settings.json`; the toast goes through `notify.sh`, which resolves
  the path for both WSL (`wslpath`) and native Windows git-bash (`cygpath`) and renders
  `notify-toast.ps1`. Windows-only: on macOS/Linux, swap for your platform's notifier
  (`osascript` / `notify-send`).

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
The widget lives in ccstatusline's config dir, so reinstalling or upgrading ccstatusline
never touches it.

## What's deliberately not here

- **Secrets**: `~/.claude/.credentials.json`, MCP auth tokens. Re-auth per machine.
- **Plugin content**: plugin-shipped skills, commands, and hooks. Installed from their
  marketplaces.
- **Local state**: `history.jsonl`, `projects/`, memory entries, `sessions/`, caches, logs.
  Runtime artifacts, not configuration (see `.gitignore`).

## License

MIT for the configuration and scripts in this repo. Plugin licenses are governed by their
upstream projects.
