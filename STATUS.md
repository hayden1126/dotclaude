# STATUS: dotclaude repo

> Living state. Update at the end of every working block so a fresh session can resume from here after `/clear`.
> Forward-looking only: current state and next steps. Git holds the history; memory holds durable decisions
> (`dotclaude-handoff-skill`, `dotclaude-research-sourcing-skill`, `dotclaude-chrome-devtools-wsl`). Per-effort
> design rationale lives in its plan under `~/.claude/plans/`.

Last updated: 2026-07-10
Branch: feat/chrome-devtools-wsl (off `main` at `4df5a49`). Pushed; PR #13 open. Base is `main`.

## Done
- **WSL2 `chrome-devtools-mcp` fix (opt-in).** The plugin's default server fails to launch Chrome on WSL2
  (`Protocol error ... Target closed`). Added a machine-local override plus docs, committed this session
  (base `4df5a49`; `git log 4df5a49..HEAD`):
  - `setup-chrome-wsl.sh` (repo root, executable): idempotent, WSL-gated installer. Installs Chrome for
    Testing into `~/chrome` (no sudo), symlinks `~/chrome/current` -> the versioned binary, checks shared
    libs (prints the `apt-get` line if any are missing), smoke-tests headless, then registers a
    **user-scoped** `chrome-devtools` MCP override in `~/.claude.json` (pinned `chrome-devtools-mcp@1.5.0`,
    `--executablePath` + `--headless` + `--chromeArg=--no-sandbox` + `--chromeArg=--disable-dev-shm-usage`).
  - `docs/chrome-devtools-wsl.md`: Strategy A (default: headless Linux Chrome, autonomous) and Strategy B
    (attach to real Windows Chrome via `--browserUrl=http://localhost:9222`, viable here because this
    machine's `.wslconfig` sets `networkingMode=mirrored`).
  - `chrome-debug.ps1` (repo root): Windows launcher for Strategy B.
  - `README.md` + `docs/PLUGINS.md`: discovery pointer + 3 rows in the "What's in here" manifest; PLUGINS
    entry reworded to "works out of the box on Linux/macOS; WSL2 users run the opt-in fix."
  - Verified end-to-end: raw MCP `navigate_page`/`take_snapshot` passed, and `claude mcp get chrome-devtools`
    reports `Status: ✔ Connected`.
  - Design: user scope outranks the plugin-provided server of the same name (precedence local > project >
    user > plugin; the whole entry wins, fields are not merged), so the plugin's skills stay while its broken
    default server is shadowed. Machine-local state (`~/chrome`, `~/.claude.json`) is deliberately outside the
    repo, and the fix is NOT wired into `setup.sh`, so non-WSL users are unaffected.

## In flight
- PR #13 open (https://github.com/hayden1126/dotclaude/pull/13), awaiting review/merge.

## Blocked / decisions needed
- None. PR #13 is open; merge at will.

## Notes for next session
- Next concrete step: review/merge PR #13. To activate the fix in a live session on THIS machine, fully
  restart Claude Code; `/mcp` should then list `chrome-devtools` as Connected and the browser tools work with
  no manual Chrome launch.
- A fresh clone on a new WSL machine needs `./setup-chrome-wsl.sh` run once (the override is in `~/.claude.json`
  user scope, not the repo). Non-WSL machines need nothing.
- Prior shipped work (all merged, see `git log`): research-sourcing skill (PR #10), staged-reader-review
  bundle upgrade, danger-guard auto mode, statusline ctx chips (PR #12).
- Deferred work (also in memory `dotclaude-handoff-skill`): (1) the deterministic PreCompact/Stop safety-net
  hook, revisit only after testing the `SessionStart` `compact`-matcher re-inject path (bug #15174), distinct
  from the shipped `UserPromptSubmit` reminder hook. (2) the autonomous loop-engineering handoff (a Python
  orchestrator step that refreshes the RESUME block).
- Evaluated and SKIPPED, do not re-raise: (a) wiring `handoff-reminder.sh` into the loop-engineering inner
  loop (the puppet gets one machine prompt with no wrap-up phrase, so the hook has no addressee; the skill
  already inherits there); (b) cross-platform notifiers (osascript / notify-send) for the toast (YAGNI on this
  WSL-only setup; README documents the manual macOS/Linux swap).
- Commit ranges: this session base `4df5a49` (chrome-devtools WSL fix); research-sourcing `3b25aa7` (PR #10);
  danger-guard auto mode `17d7989`; handoff skill `8bb222d..681ae87`; reminder hook PR #2 `3454cc2..ab9ba6b`.
  See `git log`.
