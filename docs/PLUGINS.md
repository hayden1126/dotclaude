# Plugins

The seven plugins this setup installs, all from the official marketplace
(`anthropics/claude-plugins-official`). Authoritative source: each plugin's own repo.
`setup.sh` reads `plugins/marketplaces.json` and `plugins/enabled.json` to register and
install them.

## `superpowers`

The execution backbone. A skills framework of rigid process skills (TDD, systematic
debugging, brainstorming, plan writing and execution, subagent dispatch, verification
before completion) plus meta-skills for authoring new skills. This is the spine the lean
setup is built around.

## `code-review`

Adds the `/code-review` slash command. Reviews the current diff for correctness bugs and
cleanup opportunities at a chosen effort level, with an `ultra` mode for deep multi-agent
review in the cloud.

## `commit-commands`

Slash commands for git: `/commit` (stage and write one commit), `/commit-push-pr` (commit,
push, open a PR), and `/clean_gone` (prune local branches whose upstream is gone).

## `claude-md-management`

Tools for keeping CLAUDE.md files healthy: initialize, audit, and prune project and global
instruction files so they stay lean.

## `hookify`

Helps author and manage Claude Code hooks (settings.json lifecycle hooks) without
hand-editing JSON. Useful when extending the guardrail surface.

## `context7`

Version-accurate library documentation over MCP. Use it whenever a question touches a
library or framework version, even a well-known one, to avoid stale training data. The
research-discipline skill points here for docs lookups.

## `chrome-devtools-mcp`

Drives a real Chrome instance over the DevTools Protocol: click, type, screenshot, inspect
network and console, run traces and audits. Works out of the box on Linux and macOS. On WSL2
the stock server cannot launch Chrome; a machine-local, opt-in override fixes it (not applied
by `setup.sh`). WSL2 users: see [chrome-devtools-wsl.md](chrome-devtools-wsl.md). Everyone
else needs nothing.
