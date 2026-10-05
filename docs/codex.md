# Codex in the Claude Code workflow

OpenAI's Codex CLI paired with Claude Code, funded by the ChatGPT Pro subscription. Codex is optional and explicit: it never runs unless you invoke it. The two tools play to different strengths, Claude Code as architect and implementer, Codex as an independent reviewer and throughput executor.

## Two layers

**Layer A, parity (who Codex obeys).** Always on once Codex is installed. However Codex runs, driven by Claude or by you in a terminal, it reads the same rules Claude does.

**Layer B, the bridge (Claude driving Codex).** Two paths.
- **Interactive:** the `codex-plugin-cc` plugin (`/codex:*`). It is toggleable, and it is how you ask for reviews and rescues.
- **Scripted:** `codex-delegate` (from the `delegation` skill). It wraps `codex exec` directly, under a fixed contract:
  - Sol or Terra only, with every sub-agent's model audited;
  - the workspace-write sandbox;
  - a memory cap (via systemd-run, when it is available) and a timeout;
  - a schema-checked report;
  - a ledger row;
  - resume by thread id.

  It does not go through the plugin. The plugin leaves the model unset and drops its jobs when a session ends; see `docs/delegation.md`.

They compose: when Claude drives Codex through the bridge, Codex still obeys the Layer A rules.

## What points to what

`dotclaude` is the single source of truth; everything else is a symlink, a merge target, or an install target.

```
dotclaude/                                  ->  runtime
  codex/config.toml       merged -------->  ~/.codex/config.toml  (a local file Codex also writes)
      "read each repo's CLAUDE.md as Codex's instructions"
  codex/AGENTS.md         symlink ------->  ~/.codex/AGENTS.md
      global working rules, for Codex
  skills/<name>/          symlink ------->  ~/.codex/skills/<name>
      the portable skills only (CODEX_SKILLS in setup.sh)
  plugins/marketplaces.json  \
  plugins/enabled.json        }  setup.sh ->  claude plugin install codex@openai-codex
                                             the codex-plugin-cc plugin inside Claude Code
  skills/delegation/scripts/codex-delegate  symlink -->  ~/.local/bin/codex-delegate
  setup.sh   (wires all of the above on any machine)

Claude Code  --/codex:*-->  codex-plugin-cc  --codex app-server-->  the local codex binary
Claude Code  --codex-delegate run-->  codex exec (pinned model, sandbox, schema)  -->  the local codex binary
                                                                     both read ~/.codex/{config.toml,AGENTS.md}  (Layer A)
~/.codex/auth.json  = the ChatGPT login, stays local, never in the repo
```

A `/codex:review` call goes Claude, plugin, `codex app-server`, Codex, and Codex reads the repo's `CLAUDE.md` plus the global `AGENTS.md` on the way. One rulebook, both tools.

## Configuration mechanism

`~/.codex/config.toml` sets `project_doc_fallback_filenames = ["CLAUDE.md"]`, so Codex reads a repo's existing `CLAUDE.md` as its instruction doc when the repo has no `AGENTS.md`. An explicit `AGENTS.md` in a repo still takes precedence, so per-repo Codex-specific guidance is a drop-in override. The combined instruction cap is raised to 64 KiB (`project_doc_max_bytes`). It also pins the default model to `gpt-5.6-sol` (`model`), because Codex otherwise runs `gpt-6-astra`, which is off-limits. Pass `-m gpt-5.6-terra` for a lighter run. A sub-agent that Codex spawns without a model inherits the parent's (tested). An explicit `spawn_agent` model argument still overrides it, though, so a prompt that lets Codex spawn agents must still name the allowed models. `codex-delegate` also audits every sub-agent's model after the run. See `docs/delegation.md`.

`~/.codex/config.toml` is merged, not symlinked, because Codex writes to it: a `[projects."<path>"]` trust entry for every directory you trust, and MCP servers that other installers register (the AWS tooling added one). Through a symlink those writes landed in this repo's working tree, one `git add -A` away from publishing local paths. `codex/merge-config.py` upserts the repo's top-level keys into the local file and leaves every table alone. It is idempotent, turns an old symlink into a local copy without losing entries, and backs up an existing file to `config.toml.pre-dotclaude-<ts>` before changing it. On Python 3.11+ it checks the result with `tomllib` before writing and refuses rather than break the file; older Pythons get a warning and an unverified write. Put only top-level, single-line keys in `codex/config.toml`; per-machine settings belong in the local file.

## How to use it

Inside a Claude Code session:
- `/codex:review`: Codex read-only reviews the current diff. An independent second opinion; a different vendor catches blind spots Claude shares with itself.
- `/codex:adversarial-review`: Codex assumes the code is broken and hunts failure classes. Use before shipping anything risky.
- `/codex:rescue "<task>"`: delegate a well-specified or stuck task to Codex. Write-capable: it can edit files. Flags: `--background`, `--wait`, `--resume`, `--fresh`.
- `/codex:status`, `/codex:result`, `/codex:cancel`: manage background Codex jobs.
- `/codex:transfer`: hand the current Claude session's history to Codex.

For scripted delegation from Claude (a long build, a batch job, anything about Codex itself), use `codex-delegate run --model sol|terra --dir <repo> --brief <file>`, launched in the background. `skills/delegation/SKILL.md` §5 has the commands and exit codes.

In a terminal: `codex` or `codex exec "..."` runs Codex standalone, still under the Layer A rules, independent of the plugin.

Division of labor: Claude for architecture, implementation, and long-context or multi-file work; Codex for independent review and throughput on well-specified tasks.

## On/off control

- Nothing auto-runs. The plugin only acts on an explicit `/codex:*` command, and the Codex runtime starts lazily on first use, so an enabled plugin costs nothing at rest.
- The plugin off or on: the `/plugin` menu, disable or enable `codex@openai-codex`. This doesn't affect `codex-delegate`, which calls `codex exec` directly. Disabling removes the commands, the `codex-rescue` subagent, and the broker hooks. To make a choice the durable default across machines, set `"codex@openai-codex"` in both `plugins/enabled.json` and the baseline `settings.json`'s `enabledPlugins`; a test keeps them equal.
- The one automatic pathway is opt-in and off by default: the stop-time review gate. Turn it on with `/codex:setup --enable-review-gate` and off with `--disable-review-gate`. When on, Codex reviews each edit-producing turn and can block a stop until issues are resolved.
- Codex standalone in a terminal is never affected by the plugin's state.

## Setup on a new machine

`setup.sh` handles it: it symlinks `codex/AGENTS.md` into `~/.codex/` (or `$CODEX_HOME`), merges `codex/config.toml` into the local `config.toml` there (leaving `auth.json` and the rest of Codex's state alone), registers the `openai-codex` marketplace, installs the plugin, and links `codex-delegate` into `~/.local/bin`. After that, run `codex login` once to authenticate, then `/codex:setup` to verify.

A machine set up before the merge still has `~/.codex/config.toml` as a symlink into this repo, so Codex keeps writing here until it is migrated. Migrate with `python3 codex/merge-config.py` alone, not a full `./setup.sh` re-run (that also rewrites the live `~/.claude/settings.json` to the baseline plus the overlay, keeping only the live file's own top-level keys).

## Key facts (September 2026, subject to change)

- Codex CLI 0.154.0. Default model GPT-6-Astra.
- `codex mcp-server` (Codex as an MCP server) was removed in 0.154. Drive Codex programmatically through `codex exec --json` or `codex app-server`, not MCP. Codex is still an MCP client, and the reverse direction (Codex calling Claude via `claude mcp serve`) still works.
- The plugin `openai/codex-plugin-cc` drives Codex through `codex app-server`, so it is unaffected by that removal.
