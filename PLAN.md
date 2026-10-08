# PLAN: Star and Shelve for Claude tmux tabs

> **Status:** STATUS.md holds where this stands (build, review, install, smoke test). The
> previous PLAN.md (the tmux restore
> design) is in git (`git show 0bce6f8:PLAN.md`), and README "Tabs come back after tmux dies"
> holds its as-built behavior.

## Context

A Claude chat lives in a tmux tab. Close the tab and the chat is reachable only by digging its
id out of `claude --resume`'s picker. Hayden wants to keep chosen chats one click away, from the
tab's right-click menu:

- **Star**: a bookmark. The tab stays open and shows ★; the chat stays on a saved list until
  unstarred, however the tab later closes.
- **Shelve**: save the chat to the list and close its tab now. Reopening takes it off the list.
  It must not come back on a tmux restore.
- On `/clear` in a starred tab, the star follows the tab: the new session id becomes starred and
  the old one drops off (Hayden's call).

When the brief left a case open, the rule was: keep the chat reachable without a surprising
reopen.

## Design

**1. Store.** `$XDG_STATE_HOME/dotclaude/saved/<session_id>.json` (default `~/.local/state`),
holding `{session_id, cwd, title, transcript_path, starred, shelved, saved_at, tab: {socket,
server_start, server_pid, pane}}` (plus `opening` while a reopen starts, see `open`), written
as an fsynced tmp file plus rename. A file exists
only while `starred or shelved`. `title` is the pane title at save time with Claude's leading
glyph stripped (✳ idle, a braille spinner busy, ◐ ours). Session ids must match
`[A-Za-z0-9][A-Za-z0-9_-]{7,127}` everywhere, as in claude-restore.

**2. Which chat is in a pane.** First Claude's own live-session files,
`~/.claude/sessions/<pid>.json`: an `interactive` session whose pid is alive (`os.kill(pid, 0)`),
whose `tmux` field (`main:@4.%4`) ends in the pane id, and whose pid runs under the pane's
`#{pane_pid}` (the ppid chain from `/proc/<pid>/stat`, at most 8 levels; the field names no server
and pids get reused, so the pane id alone can match another server's pane). Its `sessionId` is updated after
`/clear`, and a tab with no registry entry still has one (verified on HAYPC 2026-10-08). This is
undocumented Claude internals, so the fallback is the registry
(`hooks/session-registry.sh`'s `open-sessions/`): the newest entry for that pane on this tmux
server with no SessionEnd `other` mark, and only while the pane's `#{pane_current_command}` is
`claude` and no live, verified sessions file puts a different chat in that pane. A claude that
crashes sends no SessionEnd, so its entry outlives it and names a pane that now runs a shell or
another chat; this gate applies everywhere the fallback is used (Star, Shelve, the menu's "this
tab", Open's "already in a pane", `rm`). The transcript is the registry's `transcript_path` when
that file exists, else the first `~/.claude/projects/*/<sid>.jsonl`.

**The ★** is the pane option `@claude_star`, since a chat is per pane: `set -p -t <pane>
@claude_star 1` and `set -pu`. `window-status-format` and the right-click menu read
`#{?@claude_star,...}` through the window's active pane (verified in tmux 3.7c).

**3. `tmux/claude-saved`** (bash, `python3 -I` for JSON; linked into `~/.local/bin` by
`setup-tmux.sh`). Every message goes to the client's status line through
`display-message -c <client>` (a run-shell has no client of its own), and nothing is printed,
since run-shell shows output in the pane.
- Star and Shelve act only in a window with a non-empty `@claude_state` (the signal that dims the
  right-click items): a registry entry can outlive its claude, and must never get a shell window
  killed. Elsewhere: "no Claude running in this tab". Both refuse a chat with no transcript yet
  ("no messages yet"), so every saved chat has one.
- `star <pane> [client]` toggles. Star records the tab and title and sets the pane's ★; unstar
  deletes the entry unless shelved and unsets it.
- `shelve [--force] <pane> [client]`: while `@claude_state` is `busy`, it asks with
  `confirm-before -b`, whose yes runs `shelve --force`. It writes the entry, deletes the chat's
  `open-sessions` file (so claude-restore won't reopen it, and the SessionEnd `other` the kill
  sends marks nothing), then kills the window, or in a split unsets the pane's ★ and kills only
  the pane.
- `menu [--remove] [client]` builds one `display-menu` as an argv array: Star (or Unstar) and
  Shelve for the client's current tab (dim when no chat is found there or no Claude runs), then
  one row per saved chat, newest first, `★` starred or `▤` shelved, title (else the repo name)
  and age, keys `1-9` then `a-z`, then Remove…, which opens the same rows running `rm`. Rows stop
  where the client's height (`#{client_height}`, less two borders, the status line and the fixed
  items) runs out, with a disabled "+N more: claude-saved list"; tmux shows no menu taller than
  the client. Nor one wider: titles are cut to `#{client_width}` less about 16 columns (borders,
  glyph, age, key), never below 8 characters, at most 40. Titles lose any `#[...]` style
  sequence (doubling `#` isn't enough: `##[` expands back to `#[`), then `#` is doubled, since
  tmux format-expands menu names.
- `open <sid> [client]` goes to the chat's pane if it runs in this server (a sessions file passes
  the same `#{pane_pid}` check; select the window in the client's session, or switch the client
  when another session holds it), stops if it runs anywhere else (a live sessions file, its
  `procStart` matching the pid's start time, that no pane here holds: outside tmux or another
  tmux server; a second live copy of a chat is the one thing open must not make), and otherwise checks the directory with claude-restore's rules (exists, no `#`,
  no control character) and the transcript, then opens a selected window in the client's session
  typing `claude --resume <id>`. It never deletes the entry: the resumed session's SessionStart
  takes it off the shelf (keeping a star), so a resume that fails to start loses nothing. After
  a successful send-keys it records `opening: {pane, server_start, server_pid, socket, at}` in
  the entry; until that SessionStart clears it, an `opening` younger than 60 s whose pane still
  exists on this server counts as the chat's pane, so opening the same row twice goes to the
  first window instead of starting a second `claude --resume <id>`.
- `rm <sid> [client]`, `list`, `-h`.
- `sync <pane>`: resolve the pane's chat and set its ★ if starred, else unset it; silent. Run by
  tmux-claude-status (below).
- `hook` (the payload on stdin; skips subagents). SessionStart: on `source == clear`, a starred
  entry whose tab is this pane on this server is re-keyed to the new id (the new file written
  before the old one is removed). Any other starred entry whose tab is this pane loses its tab
  (another chat runs there now, so a later `/clear` there isn't its). A shelved chat that starts
  anywhere in tmux leaves the shelf, and its `opening` note goes. If this chat is starred, its
  tab is refreshed and ★ set; else ★ is unset. SessionEnd refreshes a saved chat's title when the
  pane is still readable and the file still exists, and unsets ★ only on a real exit
  (`prompt_input_exit`, `logout`): after any other end (an in-session `/resume`, say) the next
  SessionStart sets or clears it, and an unset here could land after that. SessionEnd `clear`
  does nothing at all: it races the SessionStart `clear` that follows, and could recreate the
  old id or clear the new ★.

**3b. `tmux/tmux-claude-status`** (the status-bar backstop). Its `list-panes` reads each pane's
`#{?@claude_star,1,0}` and clears the ★ of any pane whose `#{pane_current_command}` isn't
`claude` (a crash with no SessionEnd, a missed exit, Ctrl-Z) and marks that pane
`@claude_star_away`. Once a marked pane runs claude again (`fg`), it runs `claude-saved sync
<pane>` (`timeout 2`, fail-open, output dropped), which puts a starred chat's ★ back, and drops
the mark. That can't wait for a cold fill: after a mid-turn Ctrl-Z, the turn's next hook sets the
window's state first. A cold-filled window (a session already going when a client attached) gets
the same sync for each claude pane.

**4. Hook wiring.** `hooks/session-registry.sh` ends by piping the same SessionStart and
SessionEnd payload to `~/.local/bin/claude-saved hook` when that is executable and `TMUX_PANE` is
set, under `timeout 3`, output dropped, fail-open. No new settings.json entry.

**5. tmux.** `tmux/claude.conf` replaces the right-click window menu with tmux 3.7c's default
plus Star/Unstar (`*`), Shelve (`v`), both dim without `@claude_state`, and Shelf… (`S`);
`bind S` opens the shelf, and `tmux/base.conf`'s Ctrl-b Enter menu ends with Star chat (`*`),
Shelve chat (`v`) and Shelf… (`S`), for a keyboard path with no Shift (Hayden's Ctrl-b S
arrived as Ctrl-b s). Both `window-status-format`s show `#{?@claude_star,★ ,}` right after the
window number, before the state glyph (claude.conf's comment says why).

**Deviations from the brief.**
- `confirm-before -t <client>`, not `-c`: in tmux 3.7c `-c` is the confirm key (man page). And
  `-b`, so the nested tmux call returns at once instead of holding the run-shell until answered.
- The client's current pane and session come from `list-clients -F`, not
  `display -p -c <client>`: `-c` picks where a message shows, while the format's pane follows
  `-t`'s default target (the best client).
- A live pane in the client's session is selected with `select-window -t <session>:<window>`
  plus `select-pane`, so a grouped view session moves its own current window, not `main`'s.
- Registry entries with an `ended_other_at` mark are ignored when resolving a pane: their claude
  was killed, so the pane runs something else.
- In the shelf menu, Shelve this tab uses key `V`, since `v` is a row key past row 30.

## Situations it must handle

| Situation | Outcome |
|---|---|
| Star a tab (sessions-file lookup) | Entry starred, `set -p ... @claude_star 1` on the pane |
| Star a tab with no sessions file (registry lookup) | Same, from the newest unmarked entry on this server |
| A stale registry entry (its claude crashed; the pane runs a shell, or another live chat) | Not the pane's chat: Star and Shelve say "no Claude session found" and kill nothing, the menu dims "this tab", Open reopens instead of jumping there, `rm` leaves that pane's ★ alone |
| Star a pane with no session anywhere | A message, no entry |
| A sessions file for the pane id whose claude doesn't run under the pane's process | Ignored; the registry decides |
| Star or Shelve where no Claude runs (stale registry entry, empty `@claude_state`) | "no Claude running in this tab", nothing written or killed; the shelf menu dims both items |
| Star with no transcript | "no messages yet", no entry |
| Unstar | Entry gone (kept if shelved), `set -pu` |
| Star, then `/clear` in the same pane | Entry re-keyed to the new id (new file first), ★ set |
| SessionEnd `clear`, before or after the SessionStart | Nothing: no title write, no ★ change |
| `/clear` in another pane, or the same pane id on another server | The starred entry is untouched |
| `/resume` of another chat in a starred tab | The star stays on the old id, ★ unset, and a later `/clear` there doesn't take it |
| A starred chat starts in a new pane (restore, reopen) | `tab` refreshed, ★ set |
| A shelved chat is resumed by hand in a tab | Off the shelf |
| SessionEnd `prompt_input_exit` or `logout` | `set -pu @claude_star`, title refreshed when the pane is readable |
| Any other SessionEnd (an in-session `/resume`, a window kill) | Title refreshed, ★ left to the next SessionStart or the backstop |
| claude dies without SessionEnd, or is suspended with Ctrl-Z | tmux-claude-status clears that pane's ★ (only that pane's, in a split) |
| `fg` after Ctrl-Z, idle or mid-turn | The pane's away mark makes the backstop run `claude-saved sync`, which sets the ★ again for a starred chat |
| Shelve | Entry shelved, registry entry deleted, kill-window (in a split: ★ unset, then kill-pane) |
| Shelve while busy | `confirm-before` issued, nothing written; `--force` does it |
| Shelve with no transcript | A message, nothing written, no kill |
| Open a shelved chat | A new window in the client's session running `claude --resume <id>`; the entry stays until that session's SessionStart takes it off the shelf |
| Open a starred chat | Reopened, entry kept, still starred |
| Open the same chat twice before its claude starts | The second open goes to the first window (its `opening` note, under 60 s); an older note is ignored |
| Open a chat already in a live pane | Its window selected (or the client switched), no new window |
| Open a chat live outside tmux or in another tmux server | A message, no new window |
| A sessions file whose pid was reused after a restart | `procStart` doesn't match: not live, so it reopens |
| Open a chat whose sessions file names a pane it doesn't run under | That file is ignored, so the chat reopens here |
| Open with the transcript gone | A message, entry kept |
| Open with the directory gone, or a `#` in it | A message, entry kept |
| Menu | Rows newest first, `★`/`▤`, keys, `#` escaped, `#[...]` styles stripped from titles |
| Menu taller than the client (35 chats, 20 lines) | 11 rows, then a disabled "+24 more: claude-saved list" |
| Menu on a narrow client | Titles cut to the width less 16 columns, never below 8 characters |
| Menu with nothing saved | The "this tab" items and a disabled "(nothing saved)" |
| Registry hook | Hands the payload on when claude-saved is executable and `TMUX_PANE` is set, skips otherwise, and still exits 0 (and cuts it off after 3 s) when claude-saved fails |

`tests/setup/test_claude_saved.py`, `tests/setup/test_session_registry.py` and
`tests/setup/test_tmux_claude_status.py` (the backstop rows) cover each row with
a stub `tmux` on PATH, a temp `HOME` and `XDG_STATE_HOME`, and fake `~/.claude/sessions` files
(the test's own pid as a live claude, a huge pid as a dead one, and the test's parent as the
pane's process, so the `/proc` ancestry check runs for real).

## Known limits

- The ★ is per pane, but the tab shows the active pane's: in a split, a starred pane that isn't
  active shows no ★ in the status bar.
- A claude that dies without SessionEnd keeps its ★ until `tmux-claude-status` sees no claude in
  that pane (a few seconds, while a client is attached).
- The backstop runs only while a client is attached, every 3 s or so: a ★ can be off for that
  long after `fg`.
- The menu shows at most 35 chats (one per key), fewer on a short client; `claude-saved list`
  shows all.

## Verification

- `python3 -m unittest discover -s tests/setup -t tests/setup` is green, and
  `bash -n tmux/claude-saved tmux/tmux-claude-status hooks/session-registry.sh` passes.
- `test_the_confs_parse_in_real_tmux` skips inside the Bash sandbox; run it outside to check the
  new binding parses.
- In real tmux (a `tmux -L probe` server, then live): right-click a Claude tab, Star (★ shows),
  `/clear` (★ stays, `claude-saved list` shows the new id), Shelve (the tab closes), Ctrl-b S
  and Ctrl-b Enter → Shelf… (both rows, ages, keys), open each, and Remove…. Check that `display-menu -c` and
  `confirm-before -b -t` from inside run-shell behave as assumed, and that Shelf… from the
  right-click menu gets the right client.
