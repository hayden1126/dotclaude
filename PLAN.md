# PLAN: relaunch open Claude tabs in tmux after a restart

> **Status (2026-10-05): built on a writer branch, not yet reviewed or live.** The previous
> PLAN.md (the deck-production geometry gate) is history; it lives in git
> (`git show 8591133:PLAN.md`), and its as-built design is in `geometry.py`'s docstring and
> deck-production's SKILL.md.

## Context

After a Windows restart or `wsl --shutdown`, the tmux server is gone, and so is every Claude tab
in `main`, one window per repo. The goal is to get them back automatically, each one resuming its
own conversation.

What existed before:
- `KeepWSLAlive` boots the VM at Windows logon. Nothing starts tmux.
- `main` is created by the first client to connect: `~/bin/tmux-remote` (ssh from the phone or
  laptop) or the PC's Windows Terminal profile (`tmux new-session -A -s main`).
- No file recorded which session ran in which tab. Hooks only knew the live `TMUX_PANE`. There was
  no SessionEnd hook, and nothing ran `claude --resume`.
- Session ids change on `/clear`, so a periodic snapshot would go stale.

Decisions:
- Trigger: when `main` is created on a new tmux server, after any death of the old one (a
  reboot, `wsl --terminate`, `tmux kill-server`). `claude-restore` can also be run by hand.
- Each tab runs `claude --resume <id>` in its own directory.
- Scope: only interactive tmux tabs still open at the restart. A tab closed on purpose stays
  closed. Background (`--bg`) sessions are out.

Rejected:
- tmux-resurrect/continuum: its 15-minute snapshots miss `/clear`. It can only `--continue`,
  which picks the wrong conversation when two tabs share a repo. And it adds TPM.
- Snapshotting from `tmux-claude-status`: it only runs while a client is attached, and it would
  mix persistence into the indicator.

## Design

**1. Registry, kept by hooks.** `hooks/session-registry.sh` (bash, `python3 -I` for JSON;
fail-open, always exits 0).
- **Where.** One file per session: `$XDG_STATE_HOME/dotclaude/open-sessions/<session_id>.json`,
  holding `{session_id, cwd, transcript_path, pane, window_index, socket, server_start, ts}`.
  One file per session means no locking, and a write is an fsynced tmp file plus rename.
  `socket` and `server_start` are tmux's `#{socket_path}` and `#{start_time}`: together they
  name the server, so a new start on the same socket means the old server died. (A boot id was
  the first design; it missed `wsl --terminate` and `kill-server`, and let a `tmux -L probe`
  server's entries compete with `main`'s.)
- **SessionStart** (startup, resume, clear, compact) writes or refreshes the file. It skips a
  session with no `TMUX_PANE`, a `-p` run (`CLAUDE_CODE_SESSION_ATTENDED=0`), a payload carrying
  `agent_id`, a `session_id` that isn't a plain token, an empty cwd, and a server it can't
  read. One call, `tmux display -p -t $TMUX_PANE '#{start_time} #{window_index} #{socket_path}'`,
  gives the server and the window (claude inherits the pane's TMUX; the path goes last, since it
  may hold a space).
- **SessionEnd** deletes the file on `prompt_input_exit` (`/exit`), `logout`, `clear`, or any
  other named reason. On `other` it only adds `ended_other_at`.

  The probe (2026-10-05) showed that `kill-window`, SIGTERM to claude and `kill-server` all fire
  SessionEnd `other`, with the hook still running. A shutdown that signals claude therefore looks
  the same as a deliberate window kill at hook time.
- **At restore, the old server's last activity** is
  `L = max(ts, ended_other_at, transcript mtime)` over the candidates, ignoring any value later
  than the current server's start (a transcript resumed by hand since is not the old end). An entry with no end mark is restored. A marked entry is restored only if
  `ended_other_at >= L - 120 s`: it died in the final batch, a shutdown. A window killed earlier,
  with later activity after it, stays closed. The bias: restoring one tab too many is cheap;
  wiping every tab is the failure the feature exists to prevent.
- **Registered in the settings baseline** (`settings.json`): a SessionStart group with matcher
  `startup|resume|clear|compact` (separate from `delegation-due.sh`'s), and a SessionEnd group.

**2. `tmux/claude-restore`** (bash; linked into `~/.local/bin` by `setup-tmux.sh`).
- **Which entries.** It reads the current server's socket and start (`tmux display`; by
  hand, after creating `main`). Candidates are entries with the same socket and a different
  start. Entries from another socket are never touched: not moved, not logged. It skips any id
  already running (`claude agents --json`, entries with a `pid`; if the call fails it carries
  on), a directory that is gone or holds a `#` (tmux format-expands `new-window -c`), and a
  marked entry outside the final batch. Then, among the survivors, it keeps the newest `ts` per
  (server start, pane). An entry with no transcript (a session writes none until its first input,
  so a tab fresh from startup or `/clear`) reopens as a plain `claude` in its directory.
- **Each restore,** in old `window_index` order: `tmux new-window -d -P -F '#{pane_id}' -t =main:
  -c <cwd>`, then `send-keys` of `claude --resume <id>` and Enter to that pane. The tab gets a
  real login shell (PATH, nvm), and the shell stays when claude exits, as tabs do today. Window
  names follow Claude's title through `claude.conf`.
- **Per entry,** its file moves to `open-sessions/restored/` just before its window opens.
  That is still before `claude --resume` runs, so the resumed session's fresh entry (it may keep
  the same id) is never swept up. If `new-window` or `send-keys` fails, it moves back, and a run
  killed midway leaves the rest in place; the next run retries both. Skipped entries move there
  too. A run with candidates first empties `restored/`, so it holds only the last restore. The
  plan passes from Python to bash with `\x1f` between fields (not a whitespace character under
  IFS, so an empty field can't shift the rest). Every decision goes to `restore.log`.
- **Flags:** `--list` (dry run, changes nothing), `--auto <name>` (hook mode: silent, and a no-op
  unless the new session is `main`), none (restore now, creating `main` detached if absent).
  `flock -n` on `open-sessions/.lock`, so `main` plus a grouped view, or a manual run racing the
  hook, restore only once.

**3. Trigger.** `tmux/claude.conf`:
`set-hook -g session-created[42] 'run-shell -b "$HOME/.local/bin/claude-restore --auto #{q:session_name}"'`.
The index keeps any session-created hook of the user's own. A full path, because tmux's PATH
lacks `~/.local/bin`. `#{q:}` shell-quotes the session name.

**4. Docs.** The README tmux section and file table, `setup-tmux.sh`'s header, STATUS, and this
file.

## Situations it must handle

| Situation | Outcome |
|---|---|
| Reboot / `wsl --shutdown`, hooks never run | Files from the old server survive, and all are restored |
| `wsl --terminate` or `tmux kill-server` | A new server start on the same socket: restored like a reboot |
| A `tmux -L probe` server on the side | Another socket: its entries are never touched, and can't hide `main`'s tabs |
| Shutdown where Claude does get SIGTERM | SessionEnd `other` marks every file within seconds; all are in the final batch, so all are restored |
| `/clear` | SessionEnd `clear` deletes the old id; SessionStart writes the new one |
| `/exit`, Ctrl-D | Deleted, not restored |
| Window killed (Ctrl-b &), work continues elsewhere | Marked, and older than the final batch, so not restored |
| Window killed, then the machine idles until tmux dies | Marked, and in the final batch, so restored (accepted: one extra tab) |
| Claude crashes, new claude in same pane | Dedupe by (server start, pane) keeps the newest |
| A transcript resumed by hand after the new server started | Ignored for the old server's last activity |
| tmux fails to open a window, or the run is killed midway | The entry stays (or moves back) for the next run |
| A `#` in the directory name | Logged and skipped |
| Two tabs in one repo | Exact ids, so each resumes its own conversation |
| `claude -p` / canary inside a pane | Skipped (ATTENDED=0) |
| `main` and a view created together, or a manual run racing | flock + server start + live check: restored once |
| Tab fresh from startup or `/clear` (no transcript yet) | Reopens as a plain `claude` in its directory |
| Directory deleted | Logged and skipped |

`tests/setup/test_session_registry.py` and `tests/setup/test_claude_restore.py` cover each row
with stub `tmux` and `claude` on PATH and a temp `XDG_STATE_HOME`.

## Verification

- `python3 -m unittest discover -s tests/setup -t tests/setup` is green.
- `test_the_confs_parse_in_real_tmux` skips inside the Bash sandbox; run it outside to check the
  `set-hook` line parses.
- Isolated end-to-end on `tmux -L probe`:
  1. Open two claude tabs (one of them `/clear`ed).
  2. Kill the server, then create `main` on the same socket (a new start time).

  No faking is needed: a new server on the same socket is exactly the trigger.

  Expect both tabs back on the right conversations, once, with `restore.log` explaining each.
  Also confirm `session-created` fires for the first session of a fresh server.
- **The real test is Hayden's** (it kills every session): `wsl --shutdown` from Windows, connect,
  and confirm the tabs return. Until then the shutdown path rests on the probe.
