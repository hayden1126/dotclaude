# Codex in the Claude Code workflow

OpenAI's Codex CLI paired with Claude Code, funded by the ChatGPT Pro subscription. Codex is optional and explicit: it never runs unless you invoke it. The two tools play to different strengths, Claude Code as architect and implementer, Codex as an independent reviewer and throughput executor.

## Two layers

**Layer A, parity (who Codex obeys).** Always on once Codex is installed. However Codex runs, driven by Claude or by you in a terminal, it reads the same rules Claude does.

**Layer B, the bridge (Claude driving Codex).** The `codex-plugin-cc` plugin. Toggleable. The only thing that lets Claude Code invoke Codex.

They compose: when Claude drives Codex through the bridge, Codex still obeys the Layer A rules.

## What points to what

`dotclaude` is the single source of truth; everything else is a symlink or an install target.

```
dotclaude/                                  ->  runtime
  codex/config.toml       symlink ------->  ~/.codex/config.toml
      "read each repo's CLAUDE.md as Codex's instructions"
  codex/AGENTS.md         symlink ------->  ~/.codex/AGENTS.md
      global working rules, for Codex
  plugins/marketplaces.json  \
  plugins/enabled.json        }  setup.sh ->  claude plugin install codex@openai-codex
                                             the codex-plugin-cc plugin inside Claude Code
  setup.sh   (wires all of the above on any machine)

Claude Code  --/codex:*-->  codex-plugin-cc  --codex app-server-->  the local codex binary
                                                                     reads ~/.codex/{config.toml,AGENTS.md}  (Layer A)
~/.codex/auth.json  = the ChatGPT login, stays local, never in the repo
```

A `/codex:review` call goes Claude, plugin, `codex app-server`, Codex, and Codex reads the repo's `CLAUDE.md` plus the global `AGENTS.md` on the way. One rulebook, both tools.

## Configuration mechanism

`~/.codex/config.toml` sets `project_doc_fallback_filenames = ["CLAUDE.md"]`, so Codex reads a repo's existing `CLAUDE.md` as its instruction doc when the repo has no `AGENTS.md`. An explicit `AGENTS.md` in a repo still takes precedence, so per-repo Codex-specific guidance is a drop-in override. The combined instruction cap is raised to 64 KiB (`project_doc_max_bytes`).

## How to use it

Inside a Claude Code session:
- `/codex:review`: Codex read-only reviews the current diff. An independent second opinion; a different vendor catches blind spots Claude shares with itself.
- `/codex:adversarial-review`: Codex assumes the code is broken and hunts failure classes. Use before shipping anything risky.
- `/codex:rescue "<task>"`: delegate a well-specified or stuck task to Codex. Write-capable: it can edit files. Flags: `--background`, `--wait`, `--resume`, `--fresh`.
- `/codex:status`, `/codex:result`, `/codex:cancel`: manage background Codex jobs.
- `/codex:transfer`: hand the current Claude session's history to Codex.

In a terminal: `codex` or `codex exec "..."` runs Codex standalone, still under the Layer A rules, independent of the plugin.

Division of labor: Claude for architecture, implementation, and long-context or multi-file work; Codex for independent review and throughput on well-specified tasks.

## On/off control

- Nothing auto-runs. The plugin only acts on an explicit `/codex:*` command, and the Codex runtime starts lazily on first use, so an enabled plugin costs nothing at rest.
- Whole bridge off or on: the `/plugin` menu, disable or enable `codex@openai-codex`. Disabling removes the commands, the `codex-rescue` subagent, and the broker hooks. To make a choice the durable default across machines, set `"codex@openai-codex"` in `plugins/enabled.json`.
- The one automatic pathway is opt-in and off by default: the stop-time review gate. Turn it on with `/codex:setup --enable-review-gate` and off with `--disable-review-gate`. When on, Codex reviews each edit-producing turn and can block a stop until issues are resolved.
- Codex standalone in a terminal is never affected by the plugin's state.

## Setup on a new machine

`setup.sh` handles it: it symlinks `codex/config.toml` and `codex/AGENTS.md` into `~/.codex/` (never the whole directory, so `auth.json` stays local), registers the `openai-codex` marketplace, and installs the plugin. After that, run `codex login` once to authenticate, then `/codex:setup` to verify.

## Key facts (September 2026, subject to change)

- Codex CLI 0.154.0. Default model GPT-6-Astra.
- `codex mcp-server` (Codex as an MCP server) was removed in 0.154. Drive Codex programmatically through `codex exec --json` or `codex app-server`, not MCP. Codex is still an MCP client, and the reverse direction (Codex calling Claude via `claude mcp serve`) still works.
- The plugin `openai/codex-plugin-cc` drives Codex through `codex app-server`, so it is unaffected by that removal.
