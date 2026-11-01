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

Each link and the `settings.json` copy land with one rename over the old entry, so an installed
path doesn't go missing mid-run, where a sandboxed command could catch it. Three cases still
remove first: a real directory in the way (moved to the backup), a real file `cp` can't read,
and any old link on git-bash, since Windows won't rename over a link to a directory.

A run also prunes installed links that no longer belong: dangling ones into this checkout, and
ones into a lane worktree (Lanes, below). When a mod or plugin changed since the last install,
it says so in one line. A session that started before the install loads those only at its start,
so it needs `/pass`.

It also sets copy mode for uv and pnpm in their user configs (`link-mode = "copy"` in
`~/.config/uv/uv.toml`, `package-import-method=copy` in `~/.config/pnpm/rc`), so a project's
installed packages are its own files, not hardlinks into the shared cache (sandbox gap N3). A
value the file already sets is kept and named on stderr. bun has no such setting. pnpm's file is
`~/Library/Preferences/pnpm/rc` on macOS, and setup then asks pnpm which value it reads. Copy
mode covers new installs only, so the run that first sets it points to `cache-unlink`: from a
terminal, `cache-unlink ~/code` counts, per project, the files that are still hardlinks into the
uv, pnpm or bun cache (`--files` lists them), and `cache-unlink --apply ~/code` gives each a copy
of its own (same bytes, mode and times; nothing to reinstall). It names every cache it searched.
A file linked to something outside the dirs you named counts too (`linked outside`: a cache it
didn't find, or harmless links such as the git objects a local `git clone` shares with its
source; un-linking those costs only disk), and so does one linked across two projects (`linked
across projects`: a store kept under them). `--keep DIR` leaves a hardlink you keep on purpose
alone. A dir it couldn't read makes the report incomplete, never clean. Run it with no Claude
session working in those dirs, since one could swap a dir for an empty one while the walk
passes. On Windows (git-bash), which has no Bash sandbox, setup skips copy mode.

**Upgrading from an older install.** Before this, the sandbox could write all of `~/.npm`,
`~/.cache/uv`, `~/.cache/pip`, `~/.cache/pnpm`, `~/.cache/node-gyp`, `~/.cache/ms-playwright`,
`~/.local/share/uv/python` and pnpm's store directly, and unsandboxed runs still use what they
hold, or what was built from it. Setup says so on every run, once the settings it replaced had
those entries, until you remove the marker it names. The rule: delete each of those dirs and
every environment built through one, put the installers themselves back from their own sources,
and only then install the rest fresh with them. In-place reinstalls aren't enough (they keep
files they don't track and links they don't reset), and an installer that came through one of
those dirs may itself hold an edit. From a terminal, with no Claude session open (plugin MCP
servers run from `~/.npm/_npx`, and deleting a live tree breaks them):
1. Note what to put back: `uv python list --only-installed --python-preference only-managed`
   (without that flag the list includes system Pythons); `uv tool list --show-with
   --show-version-specifiers --show-extras --show-python` (for a tool installed from git or a
   local path, copy its source from `~/.local/share/uv/tools/<tool>/uv-receipt.toml`); `pnpm
   ls -g`; `npm ls -g --depth=0`; `<python> -m pip list --user --format=freeze` for each
   Python you have; `pipx list`; pipx's shared dir, `pipx environment --value
   PIPX_SHARED_LIBS` (older pipx: read it off `pipx environment`; it moves with the pipx
   version and PIPX_HOME); and how you installed Node, uv, pnpm, pip and pipx.
2. Delete, by path (not through `uv cache clean`, `pip cache purge` or `pnpm store path`, which
   clear only the cache now configured, and for pnpm only its current version's folder): `rm
   -rf ~/.npm ~/.cache/uv ~/.cache/pip ~/.cache/pnpm ~/.cache/node-gyp ~/.cache/ms-playwright
   ~/.local/share/uv/python ~/.local/share/uv/tools ~/.local/share/pnpm/store
   ~/.local/share/pnpm/global ~/.local/share/pnpm/.tools <pipx's shared dir>`, and every
   environment built through those dirs: each project's `.venv`, `venv` and `node_modules`, and
   tool envs such as `.tox`, `~/.cache/pre-commit`, poetry's and hatch's envs and Jupyter
   kernels' venvs. Leave pipx's own venvs: `pipx reinstall-all` reads them, then builds each
   anew, and builds its shared pip fresh once that dir is gone. `~/.npm` holds npm's download
   cache and the trees npx reuses; `~/.cache/pnpm` pnpm's metadata and the trees `pnpm dlx`
   reuses; node-gyp's headers reached every native addon npm or pnpm built.
3. Put the installers back from their own sources, whatever installed them before, so none
   that came through those dirs runs again: Node (remove its package or nvm version, then
   install it again, which brings a fresh npm and, through Node 24, corepack); pipx from its
   distro package (after `<python> -m pip uninstall pipx` if pip installed it); uv from its
   standalone installer (after `pipx uninstall uv`
   or `<python> -m pip uninstall uv` if one of those installed it); pnpm from corepack or its
   own installer (after `npm uninstall -g pnpm` if npm installed it); and pip for a Python
   whose only pip was a `--user` one (`<python> -m ensurepip --user`, or the distro package).
4. Remove the old globals with those fresh tools: `npm uninstall -g <each>` but npm itself
   (with sudo when `npm prefix -g` is system-owned; corepack too where it is an npm global,
   from Node 25 or an `npm install -g corepack`), and `<python> -m pip uninstall <each>` user
   package but pip (add `--break-system-packages` where a distro Python refuses, here and in
   step 5).
5. Install the rest fresh: npm's and pnpm's globals (`npm install -g`, `pnpm add -g`), `uv
   python install <the versions>`, `uv tool install` each tool with what step 1 noted, each
   Python's `--user` packages (`<python> -m pip install --user`), `pipx reinstall-all`, each
   project's environment (`uv sync`, `pnpm install`, `npm ci`, a new venv) and each tool env
   above, and Playwright's browsers: `npx playwright@<each project's version> install
   chromium-headless-shell`.

A project you'd rather not rebuild can be un-linked instead (`cache-unlink --apply <dir>`): that
ends its links into the caches but keeps the bytes, so it can't undo an edit made before.

Auditing the caches against their own checksums is the alternative; HAYPC's were audited on
2026-10-31 and were clean.

Each run replaces that copy, so a value added to a key the baseline sets is lost. Settings that belong
to one machine, such as hooks for its own scripts or `sandbox.excludedCommands` for its own tools, go
in `~/.claude/settings.machine.json` instead. It isn't in this repo; `setup.sh` installs the baseline
with it merged in. Objects merge key by key, lists append (skipping items already there), and any
other value replaces the baseline's (`merge-settings.py`). Top-level keys only the live copy sets
(what `/config`, `/model` and auto mode write, such as `autoMode` and `model`) are kept. `setup.sh`
names every live value the baseline overrides (such as `effortLevel`) and every live hook command
it drops; put a value in the overlay to keep it. The baseline now owns a `permissions` object, so
`setup.sh` replaces the live one (`merge-settings.py` names it on stderr): personal allow rules go
in `settings.machine.json`, whose lists append. Installed from a checkout other than `~/dotclaude`
(a lane's worktree), the copy's `denyWrite` also names that checkout's copies of the
`~/dotclaude` paths, since the installed links point there.

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
sandboxed. Every PATH dir under your home (`~/hq/bin` on HAYPC) gets an Edit deny rule in the
overlay's `permissions.deny` (`"Edit(~/hq/bin/**)"`), or the excluded-command guard refuses every
excluded command. Only user and managed settings count for that, so a project's
`.claude/settings*.json` can't stand in. On a new machine, the first `./setup.sh` ends with the
guard's scan: it lists each dir it would refuse with what the dir holds, then prints the whole
`settings.machine.json` with the rules added. Look at each dir, paste the file, and rerun setup
where the scan's last line says. Rerun the scan (`python3 -I hooks/excluded_guard.py --scan`) after adding a
PATH dir or cloning a repo whose install step sets in-repo git hooks.

The baseline's `env` pins new sessions to Opus with `ANTHROPIC_MODEL=opus`. Without it, `/model`
saves its pick as the machine-wide default, so a `/model sonnet` in one session moves every later
session to Sonnet; with it, `/model` changes only its own session. To pin another model, set
`env.ANTHROPIC_MODEL` in the overlay. What `/model` prints under the pin, and how a `/pass`, tab
restore or shelf Open keeps a session's pick: docs/lanes.md, "Model and effort".

The baseline's `permissions` deny destructive git and ask before anything that can reach `main`,
in auto mode too. Denied: force-push, `reset --hard`, `reset --merge` and `git clean -f`, plain or
through `git -C`, plus a `bash -c` whose text has `git push` then `--force`, or `git reset` then
`--hard`. Asked: a push whose text has `main`, `HEAD`, `@`, `--all` or `--mirror`, one that names
no branch (`git push`, `git push origin`), one starting with a flag (`git push -u ...`,
`git push origin --no-verify`), a `+` force the deny rules miss, any `git -C <dir> push`, and
merges (`gh pr merge`, `gh api ...merge`). Allowed without a prompt: `git push origin <branch>`
and the PR lifecycle short of a merge (`gh pr create`, `ready`, `edit`, `comment`, `close`,
`reopen`); CLAUDE.md still has Claude ask in words first. The classifier once refused the
handoff skill's own `gh pr ready` as an unrequested commit, so `test_settings.py` now checks
that every `gh pr` or `gh run` step CLAUDE.md, a skill or an agent names has a rule. Also
allowed, because the classifier once refused a CI watch with no reason given: the read-only
`gh pr checks`, `view`, `list`, `status` and `diff`, and `gh run list`, `view` and `watch`.
`lane ls`, `new`, `adopt`, `open`, `done`, `park`, `addr` and `lead` are allowed too, behind the excluded-command guard
(docs/lanes.md S3).
Read-only git (`status`, `log`, `diff`, `show`, `rev-parse`; the classifier once refused one as an
"unrequested commit") is allowed too, with the pipe filters `head`, `tail`, `wc` and `grep`, since
every part of a pipe needs its own rule. `git ... --output` writes a file, so it asks. A `cd <dir>
&& git ...` still goes to the classifier, even with a `Bash(cd *)` rule: Claude Code sends `cd` plus
`git` there whatever the rules say. `git -C <dir> status` and the other `-C` reads go there too,
since a `git -C * log*` rule would also match a commit. A rule can't see the current branch, which
is why every form that could land on `main` without naming it asks. Not checked (accepted): flags
after the branch, remotes other than `origin`, and deleting a branch other than `main` with `origin
:branch` (no rule can match ` :` without a `:*`, which Claude Code reads as its legacy prefix form
or warns about at every start). Everything else goes to auto mode's classifier: other wrappers (any
other `bash -c`, such as one running `push -f`, and `bash -lc`, `sh -c`, `eval`), git global options
other than `-C` (`-c k=v`, `--git-dir`, `--no-pager`), soft, mixed and `--keep` resets, and
`checkout`, `switch`, `restore` and `revert`. Why rules at all: on 2.1.288, auto mode ran a
force-push and a `reset --hard` on a dirty tree when the prompt named them.

`sandbox.excludedCommands` is the allowlist of what runs outside the sandbox.
`tests/delegation/command_inventory.py` lists each entry, why it needs the outside and the calls it
must cover, and `test_settings.py` ties it to `settings.json` in both directions. It holds the
credential barrier (`git push` to `origin`, `fetch`, `pull`, `ls-remote`, and `gh`'s `pr`, `run`,
`issue`, `api` and `search` with its read-only `repo`, `release` and `auth status` forms), our
wrappers (`lane init`, `new`, `adopt`, `ls`, `open`, `done`, `addr`, `lead`, `pass-respawn`, `delegation-ledger`,
`codex-delegate`, `ed-pull`), `claude`, the read-only tmux verbs (`ls`, `list-sessions`, `list-windows`,
`list-panes`, `list-clients`, `list-keys`, `list-commands`, `capture-pane`, `display`, `show`,
`show-options`, `show-environment`, `show-messages`, `show-hooks`), read-only codex (`login status`,
`doctor` and a few lists) and the Windows shells. Each one meets `hooks/excluded-guard.sh` first
(Hooks, below). Any other call runs sandboxed, where tmux reaches
no socket, codex and any other `gh` form no credential, and a push to a local path no other repo's
hooks, so it fails closed.

Asks cover what an excluded command could still be made to run or read:
- tmux: every other verb, alias and prefix, a bare `tmux`, a global flag, a `;` chain, a `#(`
  job, the `E:` and `T:` format modifiers (they expand a value as a format) and `display -I`;
- `claude`: the flags that turn off a guard, widen the permission mode (`auto` included) or load
  config, tools, code or files from elsewhere, hidden flags included; the subcommands that change
  the install, config, auth or sessions; `plugin test` and `eval` (they run code from a chosen
  path). `claude ultrareview` is denied;
- git's `--upload-pack`, `--receive-pack` and `--exec`, in every prefix git accepts;
- `gh auth status -t`; `gh run download`, which writes where it's told; and the flags that read
  a local file and send it to GitHub (`--body-file`, `-F`, `--field`, `--input`), since denyRead
  doesn't bind an excluded command. A bundled short flag (`-dF`) gets past a glob, so it is left to
  the classifier until a guard parses gh's arguments and checks each path. These asks match
  anywhere in the command, so a `--body` whose text names one of these flags asks too;
- `lane init --setup` or `--root`, `lane done --abandon`, `codex-delegate --network` and
  `--no-scope` (these wrappers take no abbreviated flag), and the Windows shells.

The wrappers check their own path arguments the same way: `codex-delegate` refuses a `--dir` or
`--out` that is, holds or sits under a denyWrite path (codex's sandbox doesn't know that list), and
a `--brief` or `--prompt` under a denyRead path; `delegation-ledger wait` refuses such a `--log`
or `--file`. Both refuse while a user or managed settings file or `policy.toml` exists but won't
parse, since its lists can't be known. What CLAUDE.md, the skills and the agents tell Claude to run asks nothing, except
the lead's once-per-repo `lane init --root ... --setup` (a test scans them), and a suite fails
when the installed tmux, git or Claude Code has a verb or flag the inventory hasn't classified.
Spellings a glob can't anchor, such as a quoted verb, a global flag before a `claude` subcommand
or a hidden `claude` flag added after the inventory, are left to the classifier.

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
| `skills/` | The skills I authored: `coding-practices`, `research-discipline`, `research-sourcing`, `writing-voice`, `staged-reader-review`, `ebook-extract`, `deck-production`, `vetting-sources`, `handoff`, `frontend-ui-discipline`, `ui-alignment`, `delegation`, `lanes`, `pass`, `server-code` (the first practices skill: safe defaults for server handlers, enforced by `hooks/practices-check.sh`), `exam-prep` (study notes, cheat sheets, mock exams and tutoring for a course exam, staged from intake to a retro); and `autopass`, a mod (a folder with `.claude-plugin/`, which Claude Code loads from `~/.claude/skills` as `autopass@skills-dir`), not a skill | symlink per dir into `~/.claude/skills/`; a skill's `scripts/` CLI also symlinks into `~/.local/bin` when that dir exists (`deck-production` ships `deckkit`; `delegation` ships `codex-delegate`, `delegation-ledger` and `gh-public`; `lanes` ships `lane`; `handoff` ships `handoff-check`; `pass` ships `pass-respawn`; `exam-prep` ships `ed-pull`, which reads Ed Discussion, GET only); the portable ones (`CODEX_SKILLS` in `setup.sh`) also link into `~/.codex/skills/` |
| `agents/` | Delegation roles: `Explore` (overrides the built-in with a no-shell reader), `researcher`, `reviewer`, `writer`; see docs/delegation.md | symlink per file into `~/.claude/agents/` |
| `hooks/agent-spawn-guard.sh` | PreToolUse(Agent) guard: denies a `writer` spawn that doesn't pass `isolation` on the call, and a named spawn without the `team-` prefix; fails closed | symlink `~/.claude/hooks/agent-spawn-guard.sh` |
| `hooks/delegation-ledger.sh` | SubagentStart/SubagentStop hook: appends a pointer row per delegated agent to the delegation ledger; as a PostToolUse hook, sends a delegated agent its deadline nudge; never blocks | symlink `~/.claude/hooks/delegation-ledger.sh` |
| `hooks/delegation-due.sh` | SessionStart hook: runs the cheap delegation checks in the background (the quick canary on a new Claude Code version, a daily audit) and shows a line only when something is due, or when a watch needs Hayden: one whose waiter's exit reaches nobody, or one that ended while no Claude process listened; fails open | symlink `~/.claude/hooks/delegation-due.sh` |
| `hooks/subagent-policy.sh` | PreToolUse(*) policy for delegated agents only (rules in `skills/delegation/policy.toml`): no leaving the sandbox, no destructive git, no MCP writes, protected paths, the researcher allowlist, writers held to their worktree; fails closed | symlink `~/.claude/hooks/subagent-policy.sh` |
| `hooks/watch-guard.sh` | Stop hook (main thread): blocks a stop once when a `delegation-ledger wait` watch has lapsed or a background command was killed at its time limit, with the re-arm command (`skills/delegation/scripts/watch-guard`); fails open | symlink `~/.claude/hooks/watch-guard.sh` |
| `hooks/report-check.sh` | PreToolUse(SubagentHandback)/SubagentStop hook: sends a delegated role's malformed report back, at most twice; fails open | symlink `~/.claude/hooks/report-check.sh` |
| `hooks/handoff-reminder.sh` | UserPromptSubmit hook: on a wrap-up / handoff / clear-memory signal, reminds me to invoke the `handoff` skill instead of improvising it, or the `pass` skill on a terse "... and pass"; a shim over `hooks/handoff_reminder.py`, which holds the classifier | symlink `~/.claude/hooks/handoff-reminder.sh` and `handoff_reminder.py` |
| `hooks/session-title.sh` | UserPromptSubmit hook: sets the terminal tab title to `<repo> · <label>` via `sessionTitle`, so tabs are tellable apart (the repo is the one the session launched in, so a Bash `cd` doesn't rename it); the label comes from the Stop-hook Haiku cache (`.title.txt`), falling back to the current prompt's first line | symlink `~/.claude/hooks/session-title.sh` |
| `hooks/stop-ring.sh` | Stop hook: plays the Windows notify sound when a session you see finishes (a tab, a plain terminal or a mapped background session), not a subagent, an unmapped background session, a `claude -p` run, a turn that ends with an agent or shell still running for it, or one a queued notice or prompt restarts within a second, and not while the device-wide mute holds the sound (`hooks/mute_state.py`); logs each decision to `ring.log`, and writes the session's stop record (`stops/<session>.json`: time, tasks in flight, the transcript path, the replies of the last 5 turns; records older than 7 days go) for `pass-respawn`; also sets the tab glyph for a main session's Stop (busy while a counted agent or shell runs, else idle) and runs `wants_input.py` in the background, which paints the tab green when the reply wants you; a shim over `hooks/stop_ring.py` | symlink `~/.claude/hooks/stop-ring.sh` and `stop_ring.py` |
| `hooks/notify.sh` | Notification(permission_prompt) hook: pops a Windows toast, resolving the toast path per platform (WSL via `wslpath`, native Windows git-bash via `cygpath`), and rings like `stop-ring.sh`; obeys the device-wide mute: no ring while the sound is muted (the toast then shows with `-Silent`), and no toast while toasts are muted | symlink `~/.claude/hooks/notify.sh` |
| `hooks/tmux-state.sh` | Prompt, tool, SubagentStop, PermissionRequest, Notification and SessionStart hook: sets `@claude_state` (busy, wait, idle) on the tmux window the session is shown in, for the indicator in `tmux/claude.conf`; keeps a set of who holds a dialog open (`@claude_wait_by`), so the tab stays waiting until every open dialog is answered; the Stop's state is `stop-ring.sh`'s; does nothing outside tmux | symlink `~/.claude/hooks/tmux-state.sh` |
| `hooks/session-pane.sh` | Sourced by the three hooks above, not a hook: finds the tmux pane a session is shown in, and whether a person sees it; holds the glyph's wait-set helpers and `read_mute`, which reads the device-wide mute for `notify.sh` and `stop-ring.sh` | symlink `~/.claude/hooks/session-pane.sh` |
| `hooks/wants_input.py` | Not a hook: `stop-ring.sh` runs it, detached, on a main session's Stop; asks Haiku whether the reply's last 2,000 characters want the person (a question, an approval, a step only they can do) and prints `yes`, `no` or `error` with the reason and the time taken | symlink `~/.claude/hooks/wants_input.py` |
| `hooks/mute_state.py` | Not a hook: the device-wide mute's flag (`$XDG_STATE_HOME/dotclaude/mute.json`), its reader and its locked writer; `read_mute` runs `mute_state.py check` only when a flag is there, and `tmux/claude-mute` and `pass-respawn` load it; a flag it can't read mutes nothing (see Hooks, "The device-wide mute") | symlink `~/.claude/hooks/mute_state.py` |
| `hooks/haiku.py` | Not a hook: the direct Haiku Messages-API call (Claude subscription OAuth token, stdlib urllib, no API key) that `session-summary.sh` and `wants_input.py` share | symlink `~/.claude/hooks/haiku.py` |
| `hooks/context-watch.sh` | Stop, PostToolUse and SessionStart(`compact`) hook: the auto-pass watcher; writes the context size to `ctx/<session>.json` (blank after a compact until a real count lands) and, at 300k, 480k and 520k (derived from `autoCompactWindow`), tells the session to run the pass skill, or with autopass off shows you one line at 520k; a shim over `hooks/context_watch.py`, which shares `hooks/autopass_state.py` (tiers, the tab flag, on or off); fails open, with errors in `context-watch.err` in the state dir | symlink `~/.claude/hooks/context-watch.sh`, `context_watch.py` and `autopass_state.py` |
| `hooks/autopass_toggle.py` | Not a hook: the `skills/autopass` mod runs it for `/autopass on\|off\|status` (`autopass_toggle.py SESSION_ID CWD ARGS`), and it prints the one reply | symlink `~/.claude/hooks/autopass_toggle.py` |
| `hooks/pass-banner.sh` | SessionStart (`startup`) hook: after a plain `/pass` respawned the tab, shows what the old session said in its last turn, once, as a banner you see and the model doesn't (its format and caps: the shim's header); a shim over `hooks/pass_banner.py`; fails open | symlink `~/.claude/hooks/pass-banner.sh` and `pass_banner.py` |
| `hooks/pass-notice.sh` | UserPromptSubmit and PostToolUse (main thread) hook: when `pass-respawn`'s waiter dropped a `/pass`, adds its notice (`pass-notice/<session>.json` in the state dir) once as context to the session's next prompt or tool call, so the session stops waiting and says why; exits before Python when no notice is there; a shim over `hooks/pass_notice.py`; fails open, with errors in `pass-notice.err` in the state dir | symlink `~/.claude/hooks/pass-notice.sh` and `pass_notice.py` |
| `hooks/md_render.py` | Not a hook: the stdlib markdown-to-terminal renderer (bold, italic, code, links, headings, lists, code blocks, tables, wrapped by terminal cells) that the banner and `tmux/pass-last` load by path | symlink `~/.claude/hooks/md_render.py` |
| `hooks/session-registry.sh` | SessionStart/SessionEnd hook: records which session is open in which tmux tab (`$XDG_STATE_HOME/dotclaude/open-sessions/`), with the window's tab bar placement (`@tab_place`, as `place`) and the `--model` and `--effort` its claude launched with (as `model` and `effort`), for `claude-restore`; deletes the entry on `/exit` or `/clear`, marks it when the window or claude is killed; then hands each payload to `claude-saved` (Star and Shelve; the star follows `/clear`); does nothing outside tmux | symlink `~/.claude/hooks/session-registry.sh` |
| `hooks/session-summary.sh` | Stop hook: regenerates the session's short (`<=32`-char) tab label via a direct Haiku Messages-API call (`hooks/haiku.py`: Claude subscription OAuth token, stdlib urllib, no API key/jq), detached so it never blocks; caches it to `<config-dir>/session-summaries/<session_id>.title.txt` for `session-title.sh` | symlink `~/.claude/hooks/session-summary.sh` |
| `hooks/overwrite-guard.sh` | PreToolUse(Write) hook: denies a Write over a file this session hasn't read, or one that cuts a file of 1 KB or more to under a fifth; a shim over `hooks/overwrite_guard.py`; fails open | symlink `~/.claude/hooks/overwrite-guard.sh` and `overwrite_guard.py` |
| `hooks/ask-check.sh` | PreToolUse(AskUserQuestion) hook: denies a risky ask once, before the dialog, with a 5-point checklist as the reason, and lets the resend through; a shim over `hooks/ask_check.py`; fails open | symlink `~/.claude/hooks/ask-check.sh` and `ask_check.py` |
| `hooks/practices-check.sh` | PreToolUse(Edit, Write, MultiEdit) and SessionStart hook: the engine for the practices skills' `events.toml` files. It denies an edit once until its skill is loaded, denies once on a bad pattern, and re-injects the skills' must-hold lines after compaction; a shim over `hooks/practices_check.py`; fails open but reports errors at session start | symlink `~/.claude/hooks/practices-check.sh` and `practices_check.py` |
| `hooks/lane-identity.sh` | SessionStart/Stop/SessionEnd hook: tells a lane session its identity and registers it, prints one board line in a lanes repo's main checkout and relinks the lead record on a proven resume, /clear or /pass of the lead, mirrors a lane's record; a shim over `hooks/lane_identity.py`; fails open | symlink `~/.claude/hooks/lane-identity.sh` and `lane_identity.py` |
| `hooks/lane-guard.sh` | PreToolUse(Edit/Write/MultiEdit) hook: denies writes to another lane's record or the lanes CLI's data, and relative identity in status files; a shim over `hooks/lane_guard.py`; fails open | symlink `~/.claude/hooks/lane-guard.sh` and `lane_guard.py` |
| `hooks/delete-guard.sh` | PreToolUse(Bash) hook, sandbox-off commands only: denies a delete whose path uses a variable the command didn't set, a command substitution that would widen it if empty, or a top-level or home tree; a shim over `hooks/delete_guard.py`; fails open | symlink `~/.claude/hooks/delete-guard.sh` and `delete_guard.py` |
| `hooks/excluded-guard.sh` | PreToolUse(Bash) hook, excluded commands only: refuses one whose cwd resolves to another repo, whose git config or PATH a sandboxed session could write, or a `claude` or `codex` call outside the project root; a shim over `hooks/excluded_guard.py`; fails closed for excluded heads | symlink `~/.claude/hooks/excluded-guard.sh` and `excluded_guard.py` |
| `hooks/excluded-check.sh` | SessionStart hook: shows what the excluded-command guard would refuse from the session's project and PATH, with the Edit deny rule for each dir, once per change in those findings; runs `excluded_guard.py --session`; fails open | symlink `~/.claude/hooks/excluded-check.sh` |
| `hooks/memory-git.sh` | SessionStart/Stop hook: commits every project's auto-memory to a local-only git repo (`$XDG_STATE_HOME/dotclaude/memory.git`); never blocks | symlink `~/.claude/hooks/memory-git.sh` |
| `hooks/blank-display.sh` | SessionStart hook: in a repo that opts in with `git config dotclaude.blankDisplay true` (every worktree of it), sets `DISPLAY` and `WAYLAND_DISPLAY` empty for Bash through `CLAUDE_ENV_FILE`, so a headed browser can't open in front of you; silent elsewhere; a shim over `hooks/blank_display.py`; fails open; see docs/chrome-devtools-wsl.md "Background Windows Chrome for probes" | symlink `~/.claude/hooks/blank-display.sh` and `blank_display.py` |
| `hooks/sandbox-caches.sh` | SessionStart hook: creates `~/.cache/claude-sandbox/<tool>` dirs and, through `CLAUDE_ENV_FILE`, exports the cache vars of npm, bun, uv, pip, pnpm, node-gyp and Playwright to them for sandboxed Bash only, so the sandbox keeps the default caches (where plugin MCP servers and unsandboxed installs run from) read-only; silent; fails open, and a sandboxed install then gets a write error | symlink `~/.claude/hooks/sandbox-caches.sh` |
| `bin/cache-unlink` | Counts, per project, the files under the dirs you name that are hardlinks into the uv, pnpm or bun cache (installs made before copy mode, sandbox gap N3; `--files` lists them); `--apply` gives each a copy of its own, writing only through dirs it opened without following a link. Links inside a cache never count; an unreadable dir makes the report incomplete. Run it from a terminal: it refuses inside the sandbox | symlink `~/.local/bin/cache-unlink` when that dir exists |
| `bin/claude-file-history` | Lists and restores Claude Code's own backups of a file (`~/.claude/file-history`), found through the transcripts | symlink `~/.local/bin/claude-file-history` when that dir exists |
| `bin/npx` | Shim ahead of the real npx: for a launch by Claude Code (an MCP server, which starts in the project dir) or an exact-version spec (`pkg@1.2.3`), it puts `--prefix=/` first, so npx ignores the project dir's `node_modules` and `.npmrc` (sandbox gap N2); anything else, such as your own `npx tsc`, reaches the real npx untouched. A hook's npx runs under `/bin/sh -c`: where that shell forks it (dash, on Debian and Ubuntu) it reaches npx untouched; where it hands a lone command over (bash, on macOS) it gets the prefix. What a project hook runs is sandbox gap H1, not the shim's. It also makes `/` npm's global prefix for that run (`npm_config_prefix=/` reaches the package). So a project's own MCP server that needs the project's registry or local install should start with `node <path>`, not npx: under the shim, `npx -y @corp/mcp` would resolve on the public registry | symlink `~/.local/bin/npx` when that dir exists (ahead of `/usr/bin` on PATH); an npx already there that isn't dotclaude's (npm's own, with npm's prefix at `~/.local`) is left alone and named |
| `bin/chrome-bg` | WSL2 only, run sandbox-off: runs Windows Chrome behind all your windows for headed puppeteer probes; `run -- CMD` hands CMD the browserURL in `$CHROME_BG_URL` and stops Chrome when CMD ends, `start`, `stop` and `ls` manage detached runs, `check` is the live self-test; see docs/chrome-devtools-wsl.md "Background Windows Chrome for probes" | symlink `~/.local/bin/chrome-bg` when that dir exists |
| `templates/` | `SPEC.md`, `PLAN.md`, `STATUS.md` scaffolds for full-track work that survive `/clear`, and `LANE.md`, a lane's record | symlink per file into `~/.claude/templates/` |
| `codex/` | Codex CLI config (config.toml baseline + AGENTS.md + merge-config.py); see docs/codex.md | symlink `AGENTS.md` into `~/.codex/`; merge `config.toml`'s keys into the local `~/.codex/config.toml` (Codex writes to it, so it is never linked; `auth.json` stays local) |
| `notify-toast.ps1` | Windows toast script that `notify.sh` renders for the Notification hook (and `pass-respawn` for a refused `/pass`); `-Silent` turns off Windows' own toast chime, which both pass while the device-wide mute holds the sound | symlink `~/.claude/notify-toast.ps1` |
| `plugins/marketplaces.json` | Marketplaces to register | consumed by `setup.sh` |
| `plugins/enabled.json` | Plugins to install and enable (must equal the baseline `settings.json`'s `enabledPlugins`; a test pins it) | consumed by `setup.sh` |
| `statusline/ctx-breakdown.py` | ccstatusline widget: colored per-category context chips (system prompt, tools, agents, memory, skills, MCP, messages); the total chip colors by the auto-pass tiers, ends in `A` when auto-pass is on, and the widget writes the model's window for the watcher (imports `hooks/autopass_state.py` through its real path) | symlink `~/.config/ccstatusline/ctx-breakdown.py` |
| `statusline/ccstatusline-settings.json` | ccstatusline layout baseline that wires the ctx-breakdown widget in | installed by `setup.sh` to `~/.config/ccstatusline/settings.json` (paths patched per machine); an existing file that isn't a readable JSON object, has a malformed `lines` list, nests too deep to write back or lacks the ctx widget is backed up to `settings.json.pre-dotclaude-<ts>` first, and one an earlier install gave the retired session-summary rows loses them; the write goes through a copy renamed into place, and a destination that isn't a regular file (a directory, a dangling link) or can't be backed up or written is left alone with a warning |
| `tools.json` | Standalone CLI tools (ccstatusline via bun) | consumed by `setup.sh` |
| `docs/PLUGINS.md` | One-line description of each plugin | reference |
| `docs/delegation.md` | Delegation hardening: design, verified facts, known gaps, install order, next stages | reference |
| `docs/prose-is-not-a-permission.md` | Blog post on the delegation work: why a prompt can't limit an agent's authority, and the layers that can | reference |
| `docs/images/` | The post's diagram: `delegation-layers.svg` (source) and `delegation-layers.png` (2x render) | reference |
| `tests/delegation/` | Unit tests for the delegation pieces (no model calls) and `run.py`, a live harness that spends model calls | run from the repo root |
| `tests/practices/` | The server-code security eval: `run.py` runs live `claude -p` sessions on planted-bug tasks in a small Next-shaped app and grades each with a hidden oracle under bwrap (spends model calls, runs sandbox-off), and `test_oracles.py` proves each oracle offline against good and bad overlays (no model calls) | `python3 -m unittest discover -s tests/practices -t tests/practices`; `run.py` by hand from the repo root |
| `tests/setup/` | Unit tests for `merge-settings.py`, `git/install-ignore.py`, and the prompt and session hooks (`handoff_reminder.py`, `session-title.sh`, `session-summary.sh`), the tmux and sound hooks (`test_tmux_hooks.py`), the device-wide mute's flag (`test_mute_state.py`), its CLI, bar mark and menu (`test_claude_mute.py`) and the toast's `-Silent` (`test_notify_toast_ps1.py`, reading `notify-toast.ps1` statically), `tmux/tmux-claude-status` (`test_tmux_claude_status.py`), the restore after tmux dies (`test_session_registry.py`, `test_claude_restore.py`), Star and Shelve (`test_claude_saved.py`), the grouped tab bar (`test_tmux_tab_bar.py`), the replies across a pass (`test_pass_banner.py`, `test_pass_last.py`, `test_md_render.py`), the drop notice (`test_pass_notice.py`), the auto-pass watcher and `/autopass` (`test_context_watch.py`), the ctx widget's tiers, cue and window write (`test_ctx_breakdown.py`), `setup-tmux.sh` (`test_setup_tmux.py`; its one-rename links and `~/.tmux.conf` write in `test_setup_tmux_link.py`), the overwrite and delete guards, the ask check (`test_ask_check.py`), the practices check (`test_practices_check.py`, which also runs every `practices_samples/*.toml` sample against its skill's `events.toml`), `memory-git.sh`, `claude-file-history`, Alt+V's inbox and the laptop scripts (`test_paste_inbox.py`; its real tmux and Windows PowerShell cases run only outside the sandbox), the display hook (`test_blank_display.py`), the sandbox caches hook (`test_sandbox_caches.py`), `chrome-bg` with its supervisor (`test_chrome_bg.py` on a fake supervisor and CDP server, `test_chrome_bg_ps1.py` reading `chrome-bg.ps1` statically; nothing launches Chrome; see docs/chrome-devtools-wsl.md), and the clock guard (`test_clock_use.py`: tests time durations with `time.monotonic()`, and a real epoch stamp keeps `time.time()` with `# wall clock` ending its line); `replay_history.py` is a local-only replay tool, not a unit test | `python3 -m unittest discover -s tests/setup -t tests/setup` |
| `tests/deck_production/` | Unit tests for `deck-production`'s `deckkit geometry` gate (rule matrix on canned probe output, plus an end-to-end run over the synthetic `fixtures/geodeck` that skips without a headless Chrome) `deckkit regress`'s geometry facts, and `deckkit doctor`'s exit codes | `python3 -m unittest discover -s tests/deck_production -t tests/deck_production` |
| `tests/lanes/` | Unit tests for the `lane` CLI, the lane hooks and `handoff-check`, on a throwaway bare origin plus clone (no network) | `python3 -m unittest discover -s tests/lanes -t tests/lanes` |
| `tests/exam_prep/` | Unit tests for `exam-prep`'s scripts (the notes build, page and print checks, the mock key and leak checks, coverage and extract checks, `ed-pull` on a fake Ed API) on synthetic fixtures, plus checks on the skill's own files (`test_skill_files.py`: no em dashes, cited ids defined, and no string from the private denylist `~/scratch/exam-prep/denylist.txt` when that file exists); no model calls, no network; the headless-browser cases run only with `EXAM_PREP_PLAYWRIGHT` set | `python3 -m unittest discover -s tests/exam_prep -t tests/exam_prep` |
| `tests/pass/` | Unit tests for `pass-respawn` on fakes for tmux, the session file and the transcript (`test_pass_respawn.py`), plus its guards and checks on the pass docs (`test_pass_guards.py`); nothing reaches the live tmux server | `python3 -m unittest discover -s tests/pass -t tests/pass` |
| `skills/autopass/tests/` | The `/autopass` mod's tests: registration, the args reaching the script, the reply as a notice mid-turn (from Enter) and as output when idle, a prompt that starts no turn (dropped, failed or a built-in), a subagent's or an interrupted turn's end, unreadable state, and a failing script (the test stands for the engine; nothing runs on the host) | `claude plugin test skills/autopass` |
| `docs/lanes.md` | Lanes: the incident, the five invariants, the communication model, the layout and the spike results | reference |
| `docs/blind-overwrite-brief.md` | Why the overwrite guard and `memory-git.sh` exist: two incidents (a blind overwrite of a memory file, a job's state inferred instead of read), the experiments and the design calls | reference |
| `docs/chrome-devtools-wsl.md` | WSL2-only: how to make `chrome-devtools-mcp` work (Strategy A headless Linux Chrome, plus B to attach to your Windows Chrome), and `chrome-bg` with the display hook for headed probes | reference |
| `chrome-debug.ps1` | Windows launcher for Strategy B (Chrome with a remote-debugging port) | run on Windows when needed |
| `chrome-bg.ps1` | The Windows half of `bin/chrome-bg`: one supervisor per run that launches Chrome through WMI, keeps its windows at the bottom of the z-order, logs their events, and kills the run's Chrome when its owner goes away; see docs/chrome-devtools-wsl.md "Background Windows Chrome for probes" | not installed: `bin/chrome-bg` runs it from beside its own real path |
| `tmux/` | The tmux side of the indicator: `claude.conf` (titles, status bar, the ◐ busy and ✳ waiting glyphs), the optional `base.conf` (mouse, splits, the Ctrl-b Enter menu), `cheatsheet.txt`, `tmux-claude-status`, the backstop the status bar runs (it also maps background sessions to their tab and has `claude-saved track` record attach tabs for `claude-restore`), `claude-restore`, which reopens `main`'s Claude tabs after the tmux server dies, `claude-saved`, which stars and shelves a tab's chat (the tab's right-click menu, Ctrl-b S, or Ctrl-b Enter), `pass-last`, which shows what Claude said before a `/pass` (Ctrl-b Up, or either menu), `paste-inbox`, which pastes a screenshot or file sent from another device (Alt+V; see Hooks, "Paste a screenshot or file from another device"), `tmux-tab-bar`, which lays out the status bar in up to 5 rows grouped by project and moves tabs you arrange by hand, and `claude-mute`, which mutes the ring and the toasts for every Claude session on the machine (Ctrl-b Enter, Mute…; a mark on the bar; see Hooks, "The device-wide mute") | sourced and linked by `setup-tmux.sh` |
| `setup-tmux.sh` | Opt-in tmux installer: links `tmux-claude-status`, `claude-restore`, `claude-saved`, `pass-last`, `paste-inbox`, `tmux-tab-bar` and `claude-mute` into `~/.local/bin` and keeps a marked `source-file` block in `~/.tmux.conf` (`--base` adds `base.conf` and the cheatsheet, `--no-base` drops them, and a run with neither keeps what the block has); each link and the new `~/.tmux.conf` land with one rename, as `setup.sh`'s do (Quickstart), so an installed path doesn't go missing mid-run (a symlinked `~/.tmux.conf` is written through to its target) | run once per machine that uses tmux; not called by `setup.sh` |
| `laptop/` | The Windows laptop side of Alt+V: `remote-paste.ahk` (AutoHotkey v2) turns Ctrl+V of a screenshot, or of one copied file, in a tab showing the PC's tmux into an upload plus Alt+V, `remote-paste.ps1` uploads, `install-remote-paste.ps1` installs both (see Hooks, "Paste a screenshot or file from another device") | run once on the laptop; nothing on the PC installs it |
| `setup-chrome-wsl.sh` | Opt-in WSL2 installer: installs Chrome for Testing, points the plugin's server at it through `~/.config/cd4a/config.json`, and removes the old user-scoped `chrome-devtools` override | run once on WSL2; not called by `setup.sh` |
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
  question about it, praise, a delegation ("hand off X to Y"), a deferral ("do a handoff at the
  time"), "ready to clear context?" or `/handoff` itself. "pass" as the bare last item of a terse
  list ("commit, handoff and pass", "handoff and compact") gets its own reminder, naming the `pass`
  skill and its mode (Pass, below). Generic phrases
  ("wrap up", "stop here", "clear the context") count only as a whole clause, so "don't wrap up
  yet", "clear the session cache" and "stop here, then explain why" stay silent. It also stays
  silent when "handoff" is just a topic (discussing the skill or this hook), on injected content
  (task notifications, subagent and cross-session messages), and on a subagent's or teammate's
  own prompt. Advisory only: it adds context, it cannot run the skill; silent no-op
  otherwise; always exits 0 so it can never block a prompt. The shim runs
  `hooks/handoff_reminder.py` with python3 and stays silent if that fails. After changing it, replay your own typed prompts through it with
  `python3 tests/setup/replay_history.py` (local only: the history holds private names).
- **UserPromptSubmit: `session-title.sh`** (in this repo). Sets the session title (the terminal tab
  title) to `<repo> · <label>` so tabs are tellable apart. It emits the supported
  `hookSpecificOutput.sessionTitle`, not raw OSC escapes, so the title has display precedence over
  Claude's own AI title and the tab's running/idle status icons stay intact. The repo name comes from
  walking up for `.git` (no git subprocess) from `CLAUDE_PROJECT_DIR`, the directory the session
  launched in: a Bash `cd` moves the payload `cwd` but not that, so a lead that steps into an agent
  worktree keeps its own name, and a lane (launched in its worktree) shows the worktree's name. There are no
  brackets, since ListAgents prints a session as `<name> [<ref>]` and a leading `[repo]` read like a
  ref. The label is chosen by a cascade: the Stop-hook Haiku
  label (`session-summaries/<id>.title.txt`), else the first line of the current prompt, else the
  bare `<repo>`. (It used to read Claude Code's own
  `ai-title`, but CC 2.1.237 stops generating that once a custom title is set, so the hook was
  suppressing the very record it read; it now owns the label instead.) A subagent's or teammate's
  prompt, or injected content (a task notification, another agent's message), leaves the title as
  it is. Fail-open (exit 0, no output on any error). Needs python3 on PATH.
- **Stop: `session-summary.sh`** (in this repo). On each substantive turn it asks Haiku for a
  short (`<=32`-char) label naming what the session works on, cached to
  `session-summaries/<id>.title.txt`, which `session-title.sh` uses for the terminal tab title. The
  label is the reply's last `LABEL:` line; a reply without one is dropped, and so is one that
  reads as the model obeying the transcript (a label opening in the first person, or a refusal,
  "as an AI" or a request to paste or share something anywhere in the reply). Generation
  is a direct Haiku Messages-API call authenticated with the Claude subscription OAuth token read
  from `~/.claude/.credentials.json` (stdlib urllib, no API key, no jq), so it burns a little 5h/7d
  subscription quota per turn but skips the system-prompt overhead of a headless `claude -p`.
  Detached so Stop never blocks the turn; fails open (exit 0) on a missing/expired token or a failed
  call, leaving the prior label in place. A cadence gate skips regeneration when the transcript grew
  < 2KB, and the prior label is fed back in. Task notifications, agent messages and skill bodies are
  left out of the dialogue it sends, so they aren't labeled as the user's request. (Until 2026-10 it
  also wrote a 1-2 sentence summary for status lines 2-3; those rows are retired.) Needs python3 on
  PATH.
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
- **The device-wide mute**: one flag silences every Claude session on the machine. It has two
  switches. The sound switch drops the ring from `notify.sh` and `stop-ring.sh`; a toast still
  shows, without its chime (`notify-toast.ps1 -Silent`). The toast switch drops the toasts from
  `notify.sh` and from a refused `/pass`. Flip them from Ctrl-b Enter, **Mute…** (both, sound or
  toasts, for 1 hour or until unmuted; or unmute), or from a shell:
  `claude-mute on [sound|toast|all] [--for 30m|2h | --until-off]` mutes (all for 1 hour by
  default, 24 hours at most), `claude-mute off [sound|toast|all]` unmutes, and `claude-mute`
  alone shows the status. A timed mute runs out by itself. A `!` line typed at a Claude prompt
  may run inside Claude's sandbox, which can't write the flag, so use the menu or a shell outside
  Claude. While anything is muted, row 0's right end shows 🔇 for sound and 🔕 for toasts, each
  with the time left (`🔇42m 🔕2h`; no time when muted until unmuted). A `?` (`🔇?` on its own)
  means the flag can't be read in full: what can't be read mutes nothing, and `claude-mute off`
  clears it. The phone layout shows no mark. The flag is `$XDG_STATE_HOME/dotclaude/mute.json`
  (`hooks/mute_state.py` has its shape). In `ring.log`, a ring the mute silenced reads
  `quiet muted=1`, a toast it skipped `toast=muted` and one shown without its chime
  `toast=silent`; a flag that can't be read adds `mute=<why>` (`unreadable`, `malformed` or
  `error`).
- **tmux indicator**: the session's window shows busy (◐) while Claude works, waiting (✳) when
  it wants you, and nothing once it is done. `tmux-state.sh` marks it busy on a prompt or tool
  call, and waiting while a permission dialog or a question is open (not on `idle_prompt`). A
  subagent's permission dialog keeps it waiting until that dialog is answered, and two dialogs
  open at once keep it waiting until both are. A dialog no hook names an owner for (an MCP
  server's form) keeps it waiting only until the next activity, anyone's. At a Stop, `stop-ring.sh` marks it busy while an agent or shell
  the session started still runs (the rule that keeps the ring quiet), else idle, then asks
  Haiku (`wants_input.py`) whether the reply wants you: a question, an approval, a step only you
  can do. A yes paints it waiting, usually within a second or two. A failed call paints it
  waiting too, so a broken check shows as green rather than as silence. The paint lands only if
  the main session did nothing newer since that Stop, and each verdict is a
  `stop input=<yes|no|error> ... painted=<1|0|->` line in `ring.log` (`-` when it painted no
  green: a no, or a queued prompt that started the next turn, `resumed=1`, which shows busy).
  Each check is one small Haiku call on your subscription quota. A reply that leaves you a step for later ("run X when
  you're ready") often reads as a report and stays blank, and one that only announces an ask
  for later ("I'll ask when the probes come up") can still paint it waiting. A new, resumed or cleared session
  starts blank, and `claude -p` runs never set it. A
  background session has no pane of its own, so `tmux/tmux-claude-status` maps it by directory to
  the one client pane in its cwd (two background sessions in one directory map nothing, and a new
  mapping also needs a single client pane there) and writes
  `$XDG_STATE_HOME/dotclaude/tabs`, which `session-pane.sh` reads. State is per window, so two
  sessions split into one window share a glyph.
  Run `./setup-tmux.sh` once for the tmux side. A machine whose `settings.machine.json` still wires
  `tmux-state.sh` should drop those entries before `./setup.sh`, or they fire twice (an old
  Stop entry does nothing now: `idle` acts only on SessionStart).
- **The tab bar groups tabs by project**: the status bar has up to 5 rows. A repo with lanes gets
  its own row, headed by its name (`dotclaude▸`): the main checkout's tabs (`lead` plus its title),
  then each lane (its id, cut to 12 cells, plus its title), then its other worktrees. A second tab
  in the main checkout, a stray session or a shell, reads `lead²` (a third `lead³`), and `lead`
  stays on the tab holding the recorded lead's pane (else on the first: no record of a pane on this
  tmux server, or a pane that closed or sits elsewhere); a new
  lead renames tabs and moves none. Every other
  window goes on the shared row(s) at the bottom, as `repo: title`. A window counts as whatever
  its active pane's directory is in. Window numbers never change; only the order on the bar does.
  Every row starts with the same gutter (the delegation token's width, then the widest repo
  header), so the first tab of every row starts in the same column; row 0 shows the token there,
  a repo's rows show its header, and the shared rows leave it blank.
  Each tab has a fixed width (the numbers live in `tmux/tmux-tab-bar`), left-justified, with a dim
  `│` between two tabs; a row with too many tabs for that splits its width evenly, and a row
  spills over only when a tab would get too narrow (the tabs then spread evenly over the rows
  they need). Row 0's right end shows the mute's mark while anything is muted (Hooks, "The
  device-wide mute"), then the host and the clock. Widths depend only on how many
  tabs there are and the terminal's width, so a title or glyph change never moves a tab or
  resizes the panes. A tab drops the prefix of Claude's title (its ✳ or spinner glyph, then
  `repo · ` or the older `[repo] ` a tab keeps until its next prompt), since the row already
  names the project. Past 5 rows the smallest
  groups share the bottom rows behind a `┃repo▸` divider; still past 5, the bar ends in `+N`, which
  opens the window list. The window you are on is always shown. On a narrow terminal (the phone over
  ssh) the bar moves to the bottom with shorter tabs and drops the host and the clock. Tap a
  tab to switch to it; tap the tab you are on for its menu (Star, Shelve, Shelf…, Replies before
  pass, Move…, Name row…, Rename and Windows…). Right-click opens tmux's window menu, with
  **Move ◀** and **Move ▶** in place of its swaps, plus the same Claude items. Shift+Left and Shift+Right
  step through the tabs in the order the bar draws them, not by window number (wrapping from the
  last tab to the first), and Shift+Up and Shift+Down go to the tab above or below; for a window
  hidden in `+N`, left and right step by number and up and down do nothing (the same without
  `tmux-tab-bar` installed). Those four keys never reach the program in a pane.
  Tabs can also be arranged by hand. Drag a tab onto another tab to put it before or after
  that tab (by which half you let go on, unless only the other side keeps it on that line when
  the row redraws), or onto a row's left edge or empty end to make it that
  row's first or last tab; a drag that ends over a pane does nothing (no copy mode). Ctrl-b then
  Shift+arrows carry the tab you are on: left and right within its row, up and down onto the row
  above or below (Shift+arrows go, Ctrl-b Shift+arrows carry, and each Shift+arrow within the
  repeat time carries again). The tap menu's **Move…** opens a menu of the same moves (◀ ▶ ▲ ▼),
  plus **New row**, a custom row of its own below the tab's row (from a shared tab, just above
  the shared rows; nothing for a tab already alone in its row), and **Auto place**, back where
  the bar puts it; it reopens after each step, so the phone can take several without retapping.
  **Name row…** (in the tap menu and the Move menu; dim outside a custom row) names a custom row
  (its header shows `name▸`, or a bare `▸` unnamed, in one colour of its own; an empty name
  clears it). Every row header ends in the same column, its name right-aligned to the `▸`.
  Ctrl-b Enter has **Move…** and **Reset bar**, which puts every tab of the session
  back where the bar places it. A row you moved a tab into keeps the order you gave it; a new
  tab joins its end. A tab placed while its repo had no lanes (a move in the shared row places
  every tab there) returns to its repo's row once the repo has a lane; one placed while the repo
  had lanes stays put. A placement made before this rule can't say how it was made, so it may
  never reset: if one keeps a tab out of its repo's row, **Auto place** clears it. A lane tab
  outside its project's row shows as `repo·lane`. The arrangement is kept in each window's
  `@tab_place` option, so it survives `/clear` and `/pass`, and in the restore record
  (`place`), so `claude-restore` brings it back after tmux dies. A tab reopened from the Shelf
  lands at the end of its project's row.
  `tmux/tmux-tab-bar` runs from tmux hooks; from the keys, a drag's release, both tab menus and
  Ctrl-b Enter; from `claude-restore`, once after it reopens tabs; and from `tmux-claude-status`,
  which catches a directory change, a lane opening or
  closing, or a swapped window within a few seconds. It never puts a title, a directory name or a lane record into a
  tmux format (a `#[...]` in a title draws as text), never prints into a pane, and if it fails
  the bar stays as it was.
- **Tabs come back after tmux dies**: a Windows restart, `wsl --shutdown`, `wsl --terminate` or
  `tmux kill-server` ends the tmux server and every Claude tab in `main`. `session-registry.sh`
  keeps one file per open tab in `$XDG_STATE_HOME/dotclaude/open-sessions/`: the session id, its
  directory, transcript, pane, window index, the tmux server it runs under (socket path,
  start time and pid), the window's tab bar placement (`place`), and the `--model` and `--effort`
  its claude launched with (`model`, `effort`). `/exit` and `/clear` delete the old id's file (a `/clear`d tab is recorded again
  under its new id). Killing the window, claude or the tmux server only marks it, since a
  shutdown that signals claude looks the same to a hook. When `main` is next created, tmux's
  `session-created` hook runs `claude-restore --auto main`. It takes the files from the same
  socket but an earlier server (other sockets, like a `tmux -L` test server, are left alone) and opens one window per tab, in the old order, running `claude --resume <id>` in its
  directory with the session's `--model` and `--effort`, or what a later `/model` or `/effort`
  picked (a bare resume takes the pinned model and the default effort; docs/lanes.md, "Model and
  effort"). It sets each window's tab bar placement before claude starts, then lays out the
  bar once, so the tabs come back where you put them. A marked tab comes back only if it ended within 120 s of its own server's
  last activity (the shutdown itself); one closed earlier stays closed. It skips a session
  already running, a deleted directory, and an older session in the same pane (one claude runs
  in a pane at a time, so only the newest can be a live tab). A directory name with a `#` is
  skipped (tmux would expand it), and so is one with a control character. A tab with no transcript yet (fresh from startup or `/clear`: a
  session writes none until its first input) reopens as `claude` in its directory, with its
  launch flags.
  `claude-restore --list` shows what it would do and why; `claude-restore` with no flag restores
  now. If tmux fails to open a window, the entry stays for the next run. Each decision is a line in `$XDG_STATE_HOME/dotclaude/restore.log`, and
  the last restore's files stay in `open-sessions/restored/`. Known limit: a window killed just
  before tmux dies with nothing else running is in that final 120 s, so it comes back. An
  extra tab is cheap; losing every tab is what this exists to prevent. A tab attached to a
  background session (`claude attach <job>`, or a `claude --resume` of a chat running in the
  background) gets no hook file, so `tmux-claude-status` has `claude-saved track` write one,
  marked `attach`. `tmux kill-server` leaves background sessions running, so such a tab comes back
  attached to its session; after a reboot it resumes the chat. Background sessions with no tab
  are not restored.
- **Star and Shelve keep a chat after its tab closes**: right-click a Claude tab (or tap the tab
  you are on) for **Star** (a
  bookmark: the tab shows ★, and the chat stays saved until unstarred, however the tab closes)
  or **Shelve** (save the chat and close the tab now; it won't come back on a tmux restore).
  **Shelf…** in the same menu, Ctrl-b S, or the Ctrl-b Enter menu (which has all three, no Shift) lists the saved chats newest first and reopens one
  as `claude --resume <id>` in its directory, with its `--model` and `--effort` as a restore
  carries them, or goes to its pane if it is still running.
  Reopening takes a chat off the shelf; a starred one stays starred. On `/clear` in a starred tab
  the star follows the tab to the new session. Star and Shelve work only where Claude is running
  and refuse a chat with no messages yet; Shelve asks first while Claude is busy. The ★ belongs
  to the pane (a split tab shows its active pane's), `tmux-claude-status` clears it where claude
  no longer runs and restores it after Ctrl-Z and `fg`. A shelf too tall or narrow for the
  terminal ends in "+N more" and shortens titles. `tmux/claude-saved` keeps one file per chat in
  `$XDG_STATE_HOME/dotclaude/saved/` and finds a tab's chat from Claude's own
  `~/.claude/sessions/` files, falling back to the registry; `claude-saved list` prints the list.
  A tab attached to a background session (`claude attach <job>`) works the same: `claude-saved`
  reads the attach client's arguments from `/proc` and finds the session that job names. A tab
  opened from agent view, or by `claude attach <part of a name>`, names no session it can trust,
  so it isn't recognized. Shelving an attach tab also stops that session
  (`claude stop`), since closing the tab alone would leave it running unseen; reopening a chat
  that still runs in the background attaches to it. A `/clear` in such a tab doesn't move its
  star: the session's hooks can't see the tab.
- **Paste a screenshot or file from another device**: under WSL, Claude Code's Ctrl+V reads the PC's
  own Windows clipboard. So a screenshot copied on a laptop that SSHes into the PC's tmux never
  arrives (for an image, Windows Terminal sends an empty paste, and Claude Code answers that the
  same way). What Claude Code does attach is an image path that arrives as a bracketed paste, so
  **Alt+V** (`tmux/paste-inbox`, linked by `setup-tmux.sh`) pastes the path of the newest image or
  file that reached the PC in the last 10 minutes: from its inbox (`~/.cache/claude-paste`), or an
  image from Windows Downloads, where Taildrop saves (an upload from the last 30 seconds wins;
  otherwise the newest does, so a browser download on the PC can beat an older upload). Any other
  file's path lands as text, and Claude reads it with Read when you ask about it: `settings.json`
  allows that Read for the inbox, which would otherwise ask first. Once installed, Alt+V no longer
  reaches a pane's own program (less, nano, an editor). With nothing installed on the other device,
  Taildrop the screenshot to the PC (Explorer's Send with Tailscale, or a phone's share sheet), then
  press Alt+V; Alt+V takes no other file from Downloads, where browser downloads land too. On a
  Windows laptop, `laptop/` makes it one key: Ctrl+V of a screenshot, or of one file copied in
  Explorer, uploads it and presses Alt+V for you. Without it, Windows Terminal pastes a copied file
  as the laptop's own path (`C:\Users\...`), which on the PC names no file, or a different one where
  both machines share a Windows user name. It needs AutoHotkey v2, and the laptop's WSL `ssh`
  reaching an SSH port on the PC that runs a plain shell (a second Windows OpenSSH port, when port
  22 is forced into tmux), with a key that asks no passphrase and a known host entry. Clone this
  repo where the laptop's Windows can read it, then run `powershell -ExecutionPolicy Bypass -File
  laptop\install-remote-paste.ps1 -Target <user>@<pc host>` (`-Port` if not 2222). It installs into
  `%LOCALAPPDATA%\remote-paste` with a Startup shortcut, keeps the host name there and out of the
  repo, and ends with a test upload the PC checks but doesn't keep; `-Uninstall` removes it. Update
  the PC and the laptop together: a laptop ahead of the PC still sends screenshots and image files,
  but a file of another type, and the installer's test, say to update both. The hotkey acts only
  while the Windows Terminal title is a remote tmux view of the PC (`view-<pid> · ...` by default;
  `-TitlePattern` for other session names, and leave the profile's `suppressApplicationTitle` off)
  and the clipboard holds an image or one copied file or folder but no text, so a text Ctrl+V or
  several copied files never reach it; a folder gets Windows Terminal's own paste. `paste-inbox
  receive` keeps a PNG, JPEG, GIF or WebP (judged by its first bytes), or with the file's name any
  file, up to 50 MB and only once all the bytes the laptop sent arrived. A file keeps its name's
  letters, digits and extension (`Q3 report.pdf` lands as `<time>-<device>-<random>-Q3-report.pdf`),
  and a non-image named like an image is refused. Each time it receives one, it deletes its own
  images older than a day (Claude Code reads an image when it is pasted) and other files older than
  7 days; Downloads is never pruned.
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
  A transcript line that doesn't parse, or nests too deep for json, is skipped and proves nothing.
  Errors and denies are logged to `$XDG_STATE_HOME/dotclaude/overwrite-guard.log`.
- **PreToolUse(`AskUserQuestion`): `ask-check.sh`** (in this repo). Asks carried claims straight
  from an agent's report, named another live lane's file without the lane, and leaned on code
  names the user had never seen. A transcript search of 1,472 asks found these in plain sessions
  as often as in lanes, about twice as often in plan mode. A checklist sent at the moment of the
  ask fixed them; a memory line didn't. So the hook denies a risky ask once with this checklist
  as the reason (the list is also in `skills/lanes/SKILL.md`, "Who asks Hayden what"):
  1. check each claim against the code yourself; 2. name every other live lane whose file the
  ask mentions; 3. restate the scope against the brief; 4. say so when the user skipped a
  question; 5. explain each code name in plain words. An ask is risky when:
  - a subagent report came in since the user's last answer (a typed prompt, an answered ask or
    an approved plan) and at most one Read, Grep, Glob or Bash call followed it;
  - its questions hold 4 or more backticked names;
  - it names a file another live lane of the repo is changing (its branch's diff from the base,
    or its brief's Expected files line) without naming that lane.

  A deny is the only hook output the model sees before the dialog. It resends in the same turn
  (probed on 2.1.304), and the resend passes: a deny of this hook's already in the window lets
  any ask through. Each ask runs one `git rev-parse` to find its repo; the lane rule runs more
  git only when that repo has another live lane, inside a time budget (`LANE_BUDGET` in
  `hooks/ask_check.py`), and never `git status` in another lane's worktree (about 60 to 70 ms
  per ask on HAYPC). Replayed over 1,485 past asks, the report and backtick rules would have
  denied 11.2% (17.6% in plan mode). Subagent calls are skipped. Fails open: with no
  transcript, or on any error, the ask goes through. Denies go to
  `$XDG_STATE_HOME/dotclaude/ask-check.log`.
- **PreToolUse(`Edit|Write|MultiEdit`) and SessionStart: `practices-check.sh`** (in this repo).
  The shared engine for the practices skills (`server-code` so far). Each skill ships an
  `events.toml` naming the edits that are its event (a route handler, a server action, a data
  export) and a few high-precision bad patterns. The engine reads every installed skill's file,
  and the project's copy wins over `~/.claude/skills`. It acts at three levels:
  - **L1:** an edit that is a skill's event is denied once until the skill is loaded in this
    context (a Skill call, or a Read of its SKILL.md since the last compaction). The deny carries
    the event's lines, and the resend passes.
  - **L2:** a new bad pattern (a request body spread into a write, a CSV built with no formula
    guard) is denied once per file and rule. A `practices-allow: <id> <reason>` comment in the file
    suppresses it.
  - **L4:** after a compaction, it re-injects the loaded skills' must-hold lines and asks Claude
    Code to reload the skill listing (`reloadSkills`).

  Events match on the path or on the file as it will read after the edit. Bash edits aren't
  checked yet. A repo turns it off with `enabled = false` in `.claude/practices/config.toml`, or
  turns one rule off there with a reason. The engine keeps a 2 s budget under the 5 s kill. Fails
  open but loud: a crash lets the edit through, and the next session start names the error.
  Errors go to `$XDG_STATE_HOME/dotclaude/practices/errors.log`.
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
- **PreToolUse(`Bash`): `excluded-guard.sh`** (in this repo), for commands that match
  `sandbox.excludedCommands` and so run outside the sandbox. Rule: such a command must not act on
  anything a sandboxed session can write. It refuses a call whose cwd resolves to a git repo
  other than the project's, whose other git config or PATH dirs a sandboxed session could write,
  or a `claude` or `codex` call outside the project root. Fails closed for excluded heads; denies go to `$XDG_STATE_HOME/dotclaude/excluded-guard.log`.
  docs/delegation.md "The excluded-command guard" has the checks and what they don't cover.
- **SessionStart: `excluded-check.sh`** (in this repo). The same guard's view of the session's
  project and PATH, so a missing Edit deny rule shows when a session starts, not when a push gets
  refused. Shown on screen and in the model's context, once per change in its findings. Fails
  open.
- **SessionStart / Stop: `memory-git.sh`** (in this repo). Commits every project's auto-memory
  (`~/.claude/projects/*/memory/`) to a local-only git repo at
  `$XDG_STATE_HOME/dotclaude/memory.git`, so a memory file broken by any means, a Bash heredoc
  included, can be restored. Transcripts are never tracked, and the repo has no remote. A
  session that finds another one mid-commit skips, and the next trigger commits. Never blocks.
- **SessionStart (`startup`): `pass-banner.sh`** (in this repo). After a plain `/pass` respawned
  the tab, it shows what the old session said in its last turn, once, as a banner the model
  doesn't see (see Pass, below). It acts only in the same tab on the same tmux server, within
  120 s of the pass, and never in a `claude -p` run or a subagent. Fails open.
- **Stop / PostToolUse / SessionStart(`compact`): `context-watch.sh`** (in this repo). The
  auto-pass watcher (see Auto-pass, below); its `/autopass` toggle is the `skills/autopass` mod,
  not a settings hook. The PostToolUse entry skips a subagent's calls before any Python starts.
  The SessionStart entry only blanks the count after a compact. Fails open.
- **UserPromptSubmit / PostToolUse: `pass-notice.sh`** (in this repo).
  - **What it does.** When a `/pass` drops (see Pass, below), the waiter leaves the session
    a notice at `pass-notice/<session>.json` in the state dir. This hook adds it once, as
    context, to the session's next prompt or next main-thread tool call. The prompt can be
    typed or injected (an agent's hand-back, a task notice). So the session stops waiting
    and says why.
  - **Keyed by session id.** A session that restore resumed after tmux died still gets it.
  - It exits before Python starts when no notice exists, skips a subagent's calls, and fails
    open.
- **SessionStart (`startup|resume|clear|compact`) / Stop / SessionEnd: `lane-identity.sh`** (in this
  repo). In a lane it tells the session its lane id, what its worktree has checked out (a branch, or
  a detached HEAD's commit), claims, port and record, and registers it in `lane.json`; after a
  compact it adds "re-read your record". In the main checkout of a lanes repo it prints one board
  line, and on SessionStart and Stop it runs `lane lead` when the session proves it continues the
  recorded lead (a resume, a /clear or a /pass successor). On Stop and SessionEnd it mirrors the
  lane's `.lane/` into the common dir. Silent in a repo with no lanes; fails open (see Lanes,
  below).
- **PreToolUse(`Edit|Write|MultiEdit`): `lane-guard.sh`** (in this repo). In a lanes repo it
  denies a write to another lane's record or to the CLI's data under `<common-dir>/lanes/`, and
  relative identity ("another session", "this session") in a lane record or the root STATUS.md.
  A repo with no lanes is untouched. Fails open; denies go to
  `$XDG_STATE_HOME/dotclaude/lane-guard.log`.
- **SessionStart (`startup|resume|clear|compact`): `blank-display.sh`** (in this repo). In a repo
  that opts in with `git config dotclaude.blankDisplay true`, read with `--local` so every
  worktree of the repo is covered, it sets `DISPLAY` and `WAYLAND_DISPLAY` empty for Bash through
  `CLAUDE_ENV_FILE`. A headed browser started from Bash then can't open a window in front of you,
  and the model is told to use `chrome-bg run` sandbox-off for a visible one. Silent in a repo
  that hasn't opted in; `git config --unset dotclaude.blankDisplay` opts out. Fails open; errors
  go to `$XDG_STATE_HOME/dotclaude/blank-display.log`. docs/chrome-devtools-wsl.md "Background
  Windows Chrome for probes" has why the vars are empty, not unset, and why it is never a
  settings `env` entry.
- **SessionStart (`startup|resume|clear|compact`): `sandbox-caches.sh`** (in this repo). It
  gives sandboxed Bash's package managers caches of their own: it creates a dir per tool under
  `~/.cache/claude-sandbox` (the sandbox skips a missing `allowWrite` path) and appends to
  `CLAUDE_ENV_FILE` a line that exports, only when `SANDBOX_RUNTIME` is set (which the sandbox
  runtime does inside the sandbox), `npm_config_cache`, `BUN_INSTALL_CACHE_DIR`,
  `UV_CACHE_DIR`, `PIP_CACHE_DIR`, `PNPM_HOME` (pnpm's store), `npm_config_devdir` (node-gyp's
  headers), plus `UV_PYTHON_DOWNLOADS=never`. pnpm's metadata
  cache needs no var: it stays read-only and pnpm skips writing it. The default caches feed code
  that runs outside the sandbox.
  Plugin MCP servers start as `npx <pkg>@<version>` and run from `~/.npm/_npx/<hash>/`, which
  npx reuses without rechecking: with `~/.npm` writable, an edit from sandboxed Bash ran at the
  next launch (sandbox gap N1, 2026-10-25). Bun's global installs are hardlinks into
  `~/.bun/install/cache`, so the status line's `ccstatusline` script was the same file as one
  sandboxed Bash could write (N3). uv, pip, pnpm, node-gyp and Playwright are the same class
  (N3): unsandboxed installs and runs reuse what their caches hold. So every default is out of
  `allowWrite`, and `~/.cache/claude-sandbox` is the only entry. Unsandboxed commands keep the
  defaults: an excluded `claude -p` would otherwise pass the vars to its MCP servers, as a
  settings `env` entry would. The first sandboxed install of a package downloads it again;
  `allowedDomains` lists the download hosts (`nodejs.org` for node-gyp's headers). Two things
  stay your own, read-only, and come from a terminal:
  - **Pythons.** Sandboxed uv runs the ones uv installed for you, read-only, and never
    downloads one, so no session can rewrite an interpreter another project's venv points at.
    A version you lack fails with uv's own hint; run `uv python install <version>` in a
    terminal.
  - **Playwright's browsers.** Sandboxed Playwright launches the ones in its default dir
    (`~/.cache/ms-playwright`), read-only: a launch writes nothing there it needs (its
    dependency marker write fails quietly, and it rechecks the host instead). A sandboxed
    `playwright install` fails with a write error; run `npx playwright@<the project's version>
    install chromium-headless-shell` (or `chromium`) in a terminal. The exact version picks the
    revision the project's Playwright wants, and makes `bin/npx` run it outside the project
    dir, so a project's own `node_modules/playwright` never runs there. Only the headless shell
    runs in the sandbox: full Chromium dies on its single-instance socket, which the sandbox
    refuses.

  The shelf itself is shared: every sandboxed session can write `~/.cache/claude-sandbox`, so a
  session in one project can tamper with a package another project's next sandboxed install
  takes from it. npm checks the hash of what it reads from its cache, but npx reuses a package
  tree it already unpacked there without a check, so an edit to it runs in the next sandboxed
  `npx pkg@<that version>` anywhere. pnpm rehashes a store file only when its mtime moved, which
  the writer can set back; uv, pip and bun don't check. Under copy mode a uv or pnpm install, once
  made, holds files of its own, so a later edit to the shelf can't reach it; bun's installs still
  hardlink. Treat what a sandboxed install built as sandbox-made,
  whichever session built it, before running it from a terminal. Every sandboxed npm or npx run prints one
  `npm warn Unknown env config "devdir"` line: node-gyp reads its dir only from that
  npm-style var. Silent; fails open (errors go to
  `$XDG_STATE_HOME/dotclaude/sandbox-caches.log`), and a sandboxed install then gets a write
  error on the default cache.

**A file got overwritten?** Claude Code backs up a file before each tool write, outside the
working directory too, for as long as the session's transcript is kept (about 30 days). Bash
writes are not covered.
- `claude-file-history <path>` lists every backup across sessions. `--show N` prints one, and
  `--restore N` puts one back after saving the current file beside it.
- For memory, `git --git-dir="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude/memory.git" log
  --stat` goes back further and covers Bash edits.

## Lanes

Several Claude sessions can work one repo at once, each in its own git worktree beside the main
checkout: a *lane*. One shared STATUS.md broke this. A line like "another session is building
#42" read as someone else to the very session meant to build it. So lanes make identity absolute
and status single-writer:

- `lane new chart-fix --claim 42 --goal "..."` makes the worktree and branch from `origin/main`,
  copies the files `.worktreeinclude` lists, hands out a port, runs the repo's setup command and
  seeds the lane's record (`<lane>/.lane/STATUS.md`, from `templates/LANE.md`).
- `lane open chart-fix` starts the lane's session in a new tmux window, in plan mode, told to
  read its record; `--focus` switches to a session already running there. `--model` and
  `--effort` (repo defaults from `lane init`) pick its model and effort, and a plain pass, a tab
  restore and the shelf's Open keep them (docs/lanes.md, "Model and effort"). Trust the lanes root
  in Claude Code once (`lane init` prints how), or each new window waits at the trust dialog.
- `lane ls` is the board, derived live from git, gh and the session files, down to each lane's
  tmux window, context (CTX: `312k*` past the auto-pass soft tier, `523k!` past hard) and
  state (STATE: busy, idle, waiting or shell). Its `overlap` flag marks two live lanes that
  change the same file, committed or not, and the lines under the board name the files.
  `lane who 42` is the only answer to who owns #42.
- `lane addr chart-fix` (or `lane addr lead`) prints `uds:<socket>`, the SendMessage address of
  that lane's live session. A session's ListAgents name is its tab title, which changes most
  turns, and a pass gives it a new socket, so resolve the address just before each send.
  With two live sessions in the main checkout, `lane addr lead` prints the lead's: the last one
  to run a bare `lane init`, `new`, `adopt`, `open` (not `--print`), `done` or `park` that succeeds,
  or `lane lead` to take it on
  purpose (`! lane lead` at its prompt). `lane ls` names both, with their windows.
  `--repo PATH` looks in the lanes repo whose main checkout holds PATH instead of the cwd's,
  so a session in any other repo sends a dotclaude bug report to the address
  `lane addr --repo ~/dotclaude lead` prints.
- `lane lock gate -- npm run e2e` runs a shared gate under a named lock, so a second lane's run
  waits instead of colliding.
- `lane trial --run "<suite>" ...`, before a lane asks for ready, merges origin/main and every
  other live lane's commits onto it in a scratch tree and runs each suite there under the
  `suite` lock (after any the config's `trial-locks` names, such as a repo's own quiet-machine
  lock). A failed suite reruns without the other lanes, so only the merge's own failures
  count, and a conflict names the lanes it is between. A lane that conflicts with origin/main
  alone is untried, not a failure. With nothing to merge, the suites still run once on the lane
  plus origin/main (docs/lanes.md, "Cross-lane checks").
- A lane tests its change by installing from its own worktree (`lane lock install --
  ./setup.sh`), and that install holds. setup.sh refuses to run from any other lane or clone
  until the main checkout's own run relinks everything. It also refuses a lane with no commit
  past `origin/main`, so a merged lane can't take the install back.
- `lane done chart-fix` closes a merged lane in one run. It ends the lane's own sessions and
  what runs under them, proven from /proc and Claude Code's session files and never chosen by
  name or tmux window, and it refuses anything else by name. Then it archives the record and
  removes the worktree, with the registration of any tree a killed `lane trial` left in it.
  While the worktree exists, it refuses a lane whose record's Next has a
  `Keep open:` line (more PRs to come; one inside a comment counts too), or whose record has an
  unclosed `<!--` or a stray `-->`, unless given `--abandon`.
- `lane park chart-fix` frees a finished lane's cap slot while it waits its merge turn. It ends
  the lane's sessions the way `done` does and keeps the worktree, branch, record and claims. It
  refuses unless the work is pushed and handed off. `lane open chart-fix` unparks it, at most
  one lane over the cap, for its rebase and merge.
- An optional lead session triages requests into lanes, opens them on Hayden's approval and sets
  the merge order (the skill's "The lead"). After a lane's PR merges, the lane sends it
  `merged #N`, and the lead reinstalls and runs `lane done` on Hayden's standing approval. Each
  ask to Hayden has one owner, lane or lead (the skill's "Who asks Hayden what").
- `lane-identity.sh` and `lane-guard.sh` (Hooks, above) tell each session which lane it is and
  keep it out of other lanes' records.
- The handoff skill's lane mode updates the lane record, not STATUS.md, and ends with
  `handoff-check`, which fails on any gap.

A repo with no lanes is unchanged. `skills/lanes/SKILL.md` is the operating guide and
`docs/lanes.md` the design. Run `lane init` once in the main checkout to start.

## Pass

`/pass` hands a session off and restarts it fresh in its tmux pane, so the next session starts
from the status doc instead of a long context. It runs the handoff (or its delta mode, when a
handoff already ran this session), gates on `handoff-check`, and calls
`pass-respawn -C <toplevel>` last. Once the session's own turn ends (below), the script
rechecks the handoff and respawns the pane with a fresh `claude`.

- `pass compact` keeps the session and types `/compact` and the resume prompt instead. Use it
  mid-task with tacit state or with background tasks in flight, which a respawn would kill (a
  plain pass drops while they run, an in-process teammate included).
- Typed triggers: "pass" fires only as the bare last item of a terse list with an action before
  it ("handoff and pass", "commit, pass", "commit, handoff and pass"). A one-word "pass" never
  fires, since it is also a "no thanks" to an offer; `/pass` is the explicit form. "pass
  compact", "handoff and compact" and "handoff and pass compact" pick the compact mode. "a
  later pass" or "the tests pass" never fire, and a bare "handoff" never passes.
- The fresh session starts in plan mode, unless the Next block's first item (the one after any
  `Keep open:` line) carries `(approved by Hayden YYYY-MM-DD)` dated within this session. The handoff skill writes that marker only for an
  approval given in the session, and `handoff-check` fails one with a bad, older or future
  date, or when it can't find the session's start.
- It waits for this session's own turn to end, not the tab's. The session file
  (`~/.claude/sessions/<pid>.json`) shows that by reading `idle`. But Claude Code keeps it `busy`
  at the prompt while a background agent, teammate or workflow runs. Then the transcript decides:
  the turn's `turn_duration` entry or an Esc interrupt after the call, with no new turn since. The
  pass drops, with nothing changed, when work landed after the handoff (`stale`), a prompt or a
  new turn came after the call, or the status changed after the turn (`resumed`), the stop listed
  any background task but memory upkeep or an artifact watch, the pane was in copy mode, held a
  draft in the input box, showed no input box or tmux didn't answer, or, for a plain pass, the
  tab's shell had a stopped job the respawn would hang up (`busy`), the session or pane went away
  or changed (`gone`), or the turn never ended (`timeout`). A refusal (`stale`, `busy`, `timeout`,
  `failed`, an `error` in the waiter, and `partial` below) shows its cause and fix on every
  terminal attached to the pane's tmux session until a key press, plus a Windows toast (which
  obeys the device-wide mute, Hooks above: skipped while toasts are muted, and without its chime
  while only the sound is; the status-line message shows either way); `resumed`
  (but for an unreadable transcript, which is loud), `gone` and `cancelled` show one brief line in
  the status line. Fix the cause and run `/pass` again. In compact mode, copy mode, a draft or
  no input box between `/compact` and the resume prompt leaves the prompt for you to type
  (`partial`): it stays in the status line until a key press, and `pass.log` has it whole. A
  `failed` after `/compact` went out hands over the prompt too (or says to press Enter when it may
  already sit in the box), since a second `/pass`
  would compact twice. Every drop and `partial` also leave the session a `[pass]` notice
  (`pass-notice.sh`, Hooks above). It arrives as context at the session's next turn or tool call,
  and says:
  - that no pass is pending, always;
  - the cause, for a loud drop; a quiet one says less (`resumed` its reason, `gone` what
    changed, `cancelled` nothing more);
  - the fix, for a loud drop (for `partial`, and a `failed` after `/compact` went out, the
    resume prompt).

  So the session stops saying a pass is queued, even after tmux died and restore resumed it.
- A `busy` refusal names the first two tasks with their description and id (`monitor "deploy
  events" (b0fzd27l4) running`), and `pass.log` names every one. Stop a leftover from `/tasks`,
  or ask Claude to `TaskStop` it. `/pass` checks first: `pass-respawn -C <dir> --tasks` lists
  the session's tasks from its last Stop, and Claude stops the finished ones (asking you about
  any it can't place) before the handoff, in either mode.
- An *artifact watch* never blocks. The Artifact tool arms one each time it publishes a page, to
  pass your comments to Claude. `/tasks` lists it under System tasks, but Claude never sees its
  id, so it can't stop one. The respawn ends it, and `pass.log` names the page, so the fresh
  session can watch it again.
- What Claude said before a pass: a plain pass clears the pane, so the old session's replies
  would leave the screen. The fresh session shows what was said in the last turn once as a
  banner (at most 40 lines of reply and 4 KiB in all), which you see and the model doesn't. A
  turn is a run of replies to one prompt_id: a turn a background-task notice started counts as
  its own, so the last turn isn't always your last prompt. Ctrl-b Up shows the last 5 turns in a
  popup at any time, opened at the last one, as does "Replies before pass" in the Ctrl-b Enter
  menu and the tab's right-click menu (`pass-last`, linked by `setup-tmux.sh`). Without
  `setup-tmux.sh`, a cut banner names the file instead. A compact keeps the conversation, so it
  needs neither.
- Both show your side too. Each turn starts with its time and the prompt you typed (the banner
  shows its first line; the popup shows it under a green bar). A turn a task notice or an
  agent's message started says "(no prompt: a background notice)", and one whose start
  `pass-respawn` couldn't read says "(prompt not saved)". `pass-respawn` reads the prompts from the
  transcript's last 8 MiB at the pass; a slash command shows as typed and an image as `[image]`,
  and each prompt is cut at 12 lines or 1 KiB. The replies are rendered from markdown by
  `hooks/md_render.py` (stdlib, no dependency): bold, code, lists, tables and code blocks in
  color, wrapped at the width without breaking words. The popup uses `less -R`; piped
  elsewhere, `pass-last` prints plain text.
- One pass may be pending per session. `pass-respawn -C <toplevel> --cancel` ends it, until the
  waiter has begun acting; then it finishes, and `--cancel` says `too-late` (also, naming the
  outcome, when the waiter dropped or acted on its own while still holding its lock). Once the
  waiter is gone, `--cancel` says nothing is pending (`outcome=none`) and `pass.log` has what it
  did.
- `pass-respawn` is in `excludedCommands` (it needs the tmux socket), so it runs bare, and the
  allow rule `Bash(pass-respawn -C *)` keeps the auto-mode classifier from refusing it. Each
  decision appends a line to `~/.local/state/dotclaude/pass.log`.

`skills/pass/SKILL.md` is the procedure and PLAN.md ("PR 3: `/pass`") the design.

### Auto-pass

A session can hand off on its own before auto-compact (about 567k tokens with
`autoCompactWindow` at 600k). `hooks/context-watch.sh` runs on Stop, on every main-thread
tool call and when a compact ends. It reads the context size from the transcript's last assistant `usage` (none when a
compact boundary comes first: the first reply after a compact can land after its tool call's
hook, and a compact blanks the count until then), writes it to
`~/.local/state/dotclaude/ctx/<session>.json` (for every session, `claude -p` and `--bg` ones
included), and acts at three tiers. They come from `autoCompactWindow`, or from the model's
window when the ctx file says it is smaller: compact at window - 33k, hard 8% of the window
before that (at most 47k), wrap-up 7% before hard (at most 40k), soft at half the window. A
200k window gives 100k, 137k and 151k; under about 110k it stays quiet.

| Tier | Tokens | With autopass on |
|---|---|---|
| Soft | 300k | a Stop is blocked once: pass if the task is done, finish a small remainder first, do nothing if the last reply asked something |
| Wrap-up | 480k | once, on a Stop or a tool call: finish this step, then pass |
| Hard | 520k | on a Stop or a tool call, again every 20k until a pass starts: pass now |

- Only the highest tier crossed speaks, once per crossing. A drop of more than a quarter of a
  tier (at most 50k) under it, as a compact makes, re-arms it, so a count hovering at a tier
  never repeats it. The hard tier's 20k re-arm (less on a small window) pauses once the session
  calls the `pass` skill, runs `pass-respawn` or you type `/pass`, and resumes if no pass came
  40k later.
- Background work: while a subagent, shell, workflow or cloud session runs, soft and wrap-up
  wait and hard says `pass compact`. With any other task but `dream` or an artifact watch (a
  monitor, a teammate), every tier says compact mode, since `pass-respawn` would refuse a plain
  pass, and names each task with its id, so Claude stops the finished ones first. A Monitor
  counts as a monitor, though Claude Code reports it as a shell (PLAN.md A10). A tool call
  can't see the task list, so it reads the last Stop's record; with none from the last 10
  minutes, it says compact mode too, as safe whether or not anything runs.
- With autopass off, you alone see one line at the hard tier, once: "Context 521k, auto-compact
  near 567k: hand off now (/pass)."
- `/autopass on|off|status` sets it for this tmux tab, or shows the count ("unknown yet" before
  the first one, and after a compact until the next), the next tier, on or off and what set it. The `skills/autopass` mod answers it with no model turn, at once even
  when typed mid-turn: while a turn runs the reply is a dim notice, otherwise the command's
  output. Without a tab's setting,
  a lane and the lanes repo's main checkout (the lead) are on (`autopass` in the repo's lanes
  config), and elsewhere `autopass = true` in
  `~/.config/dotclaude/pass.toml` turns it on (off by default). `tiers = [soft, wrap, hard]` in
  that file overrides the tiers for live tests; start the test session with its own
  `XDG_CONFIG_HOME` so the override reaches only that session.
- Nothing fires for a subagent, a `claude -p` or `--bg` session (no pane to respawn), or while
  a pass is already pending.
- `skills/autopass` is dotclaude's first mod, on Claude Code 2.1.296's early-access mod API: it
  registers `/autopass` with `immediate`, answers `command.run`, tracks the turn from
  `prompt.submit` (Enter) through `turn.start` to `turn.complete`, and runs `hooks/autopass_toggle.py` through
  `$.process.run`, which hands the child the session's `TMUX_PANE`. If that API changes,
  `/autopass` turns into an unknown command or prints "the toggle failed"; `claude plugin
  validate skills/autopass` and `claude plugin test skills/autopass` show what broke.

PLAN.md ("PR 4: auto-pass") is the design.

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
of the window, set off from the per-category chips by a thin divider. Its color follows the
auto-pass tiers (see Auto-pass) on the smaller of the model window and `autoCompactWindow`:
green below soft, yellow from soft, dark red from wrap-up, and bold bright red "Ctx!" from
hard (300k, 480k and 520k of a 600k window). An `A` at the end of the chip means auto-pass is
on for this tab. The widget also writes the model's window into the session's ctx file, since
no hook payload carries it, so the watcher's tiers follow a smaller window. Without
`hooks/autopass_state.py` (a copied widget) it falls back to 50%, 66% and 83% of the window,
with no `A`.

The widget lives in ccstatusline's config dir, so reinstalling or upgrading ccstatusline
never touches it. The status line is one row: the session summary that once filled lines 2 and
3 is retired, and `setup.sh` takes its two widgets out of an existing layout.

## What's deliberately not here

- **Secrets**: `~/.claude/.credentials.json`, MCP auth tokens. Re-auth per machine.
- **Plugin content**: plugin-shipped skills, commands, and hooks. Installed from their
  marketplaces.
- **Local state**: `history.jsonl`, `projects/`, memory entries, `sessions/`, caches, logs.
  Runtime artifacts, not configuration (see `.gitignore`).

## License

MIT for the configuration and scripts in this repo. Plugin licenses are governed by their
upstream projects.
