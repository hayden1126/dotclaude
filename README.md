# My Claude Code setup

A portable snapshot of my global [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) configuration — settings, hooks, status line, custom agents, rules, and the plugin marketplaces I install. Run `./setup.sh` on a fresh machine (or device) and end up with the same setup.

This repo intentionally does **not** vendor plugin-owned content (skills, sub-agents, hooks from plugins like `ecc`, `superpowers`, `context-mode`, etc.) — those get installed from their own marketplaces. What lives here is what *I* wrote or curated.

## Quickstart

```bash
git clone <this repo> claude-setup
cd claude-setup
./setup.sh
claude login        # one-time auth
```

`setup.sh` is idempotent. Existing files in `~/.claude/` are backed up to `~/.claude/backups/pre-showcase-<timestamp>/` before being replaced with symlinks back to this repo.

## What's in here

| Path | What it is | Symlinks to |
|---|---|---|
| `CLAUDE.md` | Global user instructions — aggressive auto-memory mode, 8 memory types, compaction rules | `~/.claude/CLAUDE.md` |
| `settings.json` | Hooks, status line, env vars, enabled plugins, marketplaces | `~/.claude/settings.json` |
| `statusline-command.sh` | Custom agnoster-style status line with daily cost tracking | `~/.claude/statusline-command.sh` |
| `notify-toast.ps1` | WSL → Windows toast notifier for the `Notification` hook | `~/.claude/notify-toast.ps1` |
| `rules/context7.md` | Global rule: always use Context7 MCP for library docs | `~/.claude/rules/context7.md` |
| `agents/` | User-authored sub-agents (the `sourced` framework: `voice-extractor`, `prose-drafter`, `source-finder`, `sourced-helper`) | `~/.claude/agents/` |
| `plugins/marketplaces.json` | List of plugin marketplaces to register | consumed by `setup.sh` |
| `plugins/enabled.json` | List of plugins to install + enable | consumed by `setup.sh` |
| `tools.json` | Standalone CLI tools to install (GSD via `npx`, etc.) | consumed by `setup.sh` |
| `docs/PLUGINS.md` | What each enabled plugin does | reference |
| `setup.sh` | The installer | — |

## Plugins

`setup.sh` registers these marketplaces and installs the plugins listed in `plugins/enabled.json`. See `docs/PLUGINS.md` for a one-line description of each.

| Plugin | Marketplace |
|---|---|
| `superpowers` | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) |
| `context7` | anthropics/claude-plugins-official |
| `frontend-design` | anthropics/claude-plugins-official |
| `chrome-devtools-mcp` | anthropics/claude-plugins-official |
| `context-mode` | [mksglu/context-mode](https://github.com/mksglu/context-mode) |
| `claude-mem` | [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) |
| `ecc` | [affaan-m/everything-claude-code](https://github.com/affaan-m/everything-claude-code) |

## Hooks

`settings.json` wires several lifecycle hooks. Most point at `$HOME/.claude/hooks/gsd-*.{js,sh}` — those scripts are shipped by [GSD](https://github.com/affaan-m/everything-claude-code) (or the standalone "get-shit-done" toolkit), **not** this repo. If you skip the GSD install, the hooks fail-open and Claude Code keeps working; you just lose the update banner, context monitor, session-state tracking, etc.

Hooks worth knowing:

- **SessionStart**: injects auto-memory aggressive-mode reminder, checks for GSD updates, restores session state, heals `context-mode` cache.
- **Notification**: plays a Windows sound + toast (WSL setup).
- **PreToolUse on Write|Edit**: GSD prompt/read/workflow guards.
- **PostToolUse on Bash/Edit/Write/etc.**: GSD context monitor.
- **statusLine**: runs `statusline-command.sh` → daily cost + context bar.

## Manual steps after `setup.sh`

1. `claude login` — one-time auth with Anthropic.
2. GSD is auto-installed via `npx get-shit-done-cc` by `setup.sh` (see `tools.json`). If `npx` wasn't on PATH at setup time, run it manually. The `sourced` academic-writing framework (also in `tools.json`) is `installer: manual` — install separately if needed; otherwise the four agents in `agents/` are inert and can be deleted.
3. Re-auth any MCP servers (`/mcp` inside Claude Code).
4. **Non-WSL**: replace the `Notification` hook in `settings.json` with your platform's notifier (`osascript` on macOS, `notify-send` on Linux).
5. **Different home dir**: paths in `settings.json` use `$HOME`, so this should work anywhere bash expands env vars in hook commands. If your Claude Code build doesn't expand `$HOME` in hook commands, `setup.sh` will fix the symlinks but you'll need to substitute manually.

## What's deliberately *not* here

- **Secrets** — `~/.credentials.json`, MCP auth tokens. Re-auth per machine.
- **Plugin content** — `~/.claude/skills/`, `~/.claude/commands/`, `~/.claude/get-shit-done/` etc. These are installed by their respective marketplaces / installers; vendoring them would go stale immediately.
- **Local state** — `history.jsonl`, `projects/`, `session-env/`, `paste-cache/`, logs, telemetry. Those are runtime artifacts, not configuration.
- **My personal data** — daily costs, memory entries, todos, debug dumps.

## License

MIT for the configuration / scripts in this repo. Plugin licenses are governed by their respective upstream projects.
