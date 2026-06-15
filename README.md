# My Claude Code setup

A portable snapshot of my global [Claude Code](https://docs.claude.com/en/docs/claude-code/overview)
configuration: global instructions, the skills and hook I authored, durable-state templates,
settings, and the plugins I install. Run `./setup.sh` on a fresh machine and end up with the
same setup.

This is a deliberately lean, principle-driven config. It vendors only what I wrote or curated.
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
so edits in either place stay in sync.

## What's in here

| Path | What it is | Installs to |
|---|---|---|
| `CLAUDE.md` | Global instructions: working partnership, boundaries, voice, the explore -> spec -> plan -> execute -> verify -> review workflow | symlink `~/.claude/CLAUDE.md` |
| `settings.json` | Hooks, status line, env vars, enabled plugins | symlink `~/.claude/settings.json` |
| `skills/` | The skills I authored: `coding-practices`, `research-discipline`, `writing-voice`, `staged-reader-review`, `ebook-extract` | symlink per dir into `~/.claude/skills/` |
| `hooks/danger-guard.sh` | PreToolUse(Bash) guard: two-tier confirmation for destructive git and `rm` ops | symlink `~/.claude/hooks/danger-guard.sh` |
| `templates/` | `SPEC.md`, `PLAN.md`, `STATUS.md` scaffolds for full-lane work that survive `/clear` | symlink per file into `~/.claude/templates/` |
| `notify-toast.ps1` | WSL to Windows toast notifier for the Notification hook | symlink `~/.claude/notify-toast.ps1` |
| `plugins/marketplaces.json` | Marketplaces to register | consumed by `setup.sh` |
| `plugins/enabled.json` | Plugins to install and enable | consumed by `setup.sh` |
| `tools.json` | Standalone CLI tools (ccstatusline via bun) | consumed by `setup.sh` |
| `docs/PLUGINS.md` | One-line description of each plugin | reference |
| `setup.sh` | The installer | run once per machine |
| `sync.sh` | Regenerates the derived plugin lists from live `~/.claude/` | run after plugin changes |

## Plugins

`setup.sh` installs seven plugins, all from
[anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official):
`superpowers`, `code-review`, `commit-commands`, `claude-md-management`, `hookify`, `context7`,
`chrome-devtools-mcp`. See `docs/PLUGINS.md` for what each does.

## Hooks

`settings.json` wires three lifecycle hooks:

- **PreToolUse(Bash): `danger-guard.sh`** (in this repo). Two tiers. It hard-blocks
  (`deny`) never-legitimate ops (force-push, `reset --hard`, `git clean -f`) and prompts
  (`ask`) for routine-but-sensitive ops (plain push, checkout, switch, revert, `rm -rf`).
  Token-aware, so it does not trip on `git commit -m "push fix"`, and it recurses into
  `bash -c "..."` and `eval` wrappers. Fires for the main agent and all subagents. Fail-open
  on any parse error. Needs python3 on PATH.
- **Stop** and **Notification**: play a Windows sound and (on permission prompts) a toast via
  `notify-toast.ps1`. WSL setup; swap for your platform's notifier elsewhere.

## Status line

`settings.json` runs [ccstatusline](https://github.com/sirmalloc/ccstatusline) at
`$HOME/.bun/bin/ccstatusline`. `setup.sh` installs it from `tools.json` with
`bun install -g ccstatusline`. If bun is not on PATH the status line is blank but Claude Code
works fine.

## What's deliberately not here

- **Secrets**: `~/.claude/.credentials.json`, MCP auth tokens. Re-auth per machine.
- **Plugin content**: plugin-shipped skills, commands, and hooks. Installed from their
  marketplaces.
- **Local state**: `history.jsonl`, `projects/`, memory entries, `sessions/`, caches, logs.
  Runtime artifacts, not configuration (see `.gitignore`).

## License

MIT for the configuration and scripts in this repo. Plugin licenses are governed by their
upstream projects.
