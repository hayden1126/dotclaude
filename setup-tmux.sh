#!/usr/bin/env bash
# setup-tmux.sh: the tmux side of the per-window Claude indicator (◐ busy, ✳ waiting) and the
# delegation token in the status bar, and what lets a background session's hooks find its tab
# (tmux-claude-status writes that map), plus claude-restore, which reopens main's Claude tabs
# after the tmux server dies, claude-saved, which stars and shelves a tab's chat (the
# right-click menu, Ctrl-b S), pass-last, which shows what Claude said before a /pass (Ctrl-b Up),
# paste-inbox, which pastes a screenshot or file sent from another device (Alt+V),
# tmux-tab-bar, which lays out the status bar in rows grouped by project, and claude-mute, which
# mutes the ring and the toasts for every session (Ctrl-b Enter, Mute…; a mark on the bar).
# Opt-in and idempotent; setup.sh never calls it. The hook side
# (hooks/tmux-state.sh, hooks/session-registry.sh) is wired by setup.sh on every machine and does
# nothing outside tmux.
#
#   ./setup-tmux.sh           link tmux-claude-status, claude-restore, claude-saved, pass-last,
#                             paste-inbox, tmux-tab-bar and claude-mute into ~/.local/bin, source
#                             tmux/claude.conf from ~/.tmux.conf
#   ./setup-tmux.sh --base    also source tmux/base.conf (mouse, splits, the Ctrl-b Enter menu)
#                             and link the Ctrl-b h cheatsheet
#   ./setup-tmux.sh --no-base drop base.conf and the cheatsheet link
#
# The source-file lines live between markers in ~/.tmux.conf, and each run rewrites that block.
# A run with neither flag keeps base.conf as the block already has it, so a plain re-run (to link
# a new script) can't strip the mouse and menus from the next tmux server. Your own lines outside
# the block are kept; the block sits at the end, so its settings win. ~/.tmux.conf is backed up
# before any change. To remove: delete the marked block and the links (seven, eight with --base).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
TS="$(date +%Y%m%d-%H%M%S)"

say()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!!\033[0m  %s\n" "$*" >&2; }
die()  { printf "\033[1;31mxx\033[0m  %s\n" "$*" >&2; exit 1; }

base=""
for arg in "$@"; do
  case "$arg" in
    --base|--no-base)
      want=1; [ "$arg" = --no-base ] && want=0
      [ -n "$base" ] && [ "$base" != "$want" ] && die "--base and --no-base conflict"
      base=$want ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done

command -v tmux >/dev/null || die "tmux not found. Install it first (sudo apt install tmux)."
command -v python3 >/dev/null || die "python3 not found."

# Neither flag: keep base.conf if the existing block sources it. (A variable, not sed | grep -q:
# under pipefail, grep closing the pipe early fails the sed and misreads a match as none.)
if [ -z "$base" ]; then
  base=0
  if [ -f "$HOME/.tmux.conf" ]; then
    block="$(sed -n '/^# >>> dotclaude tmux (setup-tmux.sh) >>>$/,/^# <<< dotclaude tmux <<<$/p' \
      "$HOME/.tmux.conf")"
    case "$block" in *'/tmux/base.conf"'*) base=1 ;; esac
  fi
fi

# Swap helpers, copied verbatim from setup.sh's section 1 and kept equal to it by
# tests/setup/test_setup_tmux_link.py. An installed path is replaced with one rename, never
# removed and then remade, so it doesn't go missing between two commands: a sandboxed command
# that builds its config in such a gap sees nothing there. The exit trap removes the temp of a
# run that stops before its rename (an error under set -e, a Ctrl-C); rm -rf never follows a
# link.
SWAP_TMP=""
trap 'rm -rf ${SWAP_TMP:+"$SWAP_TMP"}' EXIT

# Windows refuses to rename over a link to a dir (git-bash with native symlinks), so a Windows
# shell removes the old link first. The gap is back there, but no Bash sandbox runs on native
# Windows to trip on it.
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) RENAME_OVER_LINKS=0 ;; *) RENAME_OVER_LINKS=1 ;; esac

# Point SWAP_TMP at this run's hidden temp beside $1: one dir, so the rename stays on one file
# system, and named by pid, so two runs at once (no flock on macOS or git-bash) don't share one.
# Temps beside $1 whose pid kill -0 can't signal (a run gone by a SIGKILL or a power loss, out of
# the trap's reach) are cleared, and so is one under this pid: ln and cp would follow it, and
# install-state.py would read a leftover link as a live one. A dead run's pid that another
# process has taken keeps its temp until that process ends.
swap_tmp() {
  local left
  SWAP_TMP="$(dirname "$1")/.$(basename "$1").dotclaude-$$"
  for left in "$(dirname "$1")/.$(basename "$1").dotclaude-"*; do
    kill -0 "${left##*-}" 2>/dev/null || rm -rf "$left"
  done
  rm -rf "$SWAP_TMP"
}

# Rename SWAP_TMP over $1.
swap_in() {
  if [[ $RENAME_OVER_LINKS -eq 0 && -L "$1" ]]; then rm -f "$1"; fi
  python3 -I -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' "$SWAP_TMP" "$1"
  SWAP_TMP=""
}

# Link src to dst with one rename, so dst never goes missing. A real file at dst is copied to
# dst.pre-dotclaude-<ts> first, so it stays in place until the rename replaces it. Any other real
# entry (a dir, a file cp can't read) is moved there first, leaving a gap, since rename can't put
# a link over a dir. A link needs nothing.
link() {
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    if [ -f "$dst" ] && [ -r "$dst" ]; then
      cp -p "$dst" "$dst.pre-dotclaude-$TS"
      warn "backed up the existing $dst to $dst.pre-dotclaude-$TS"
    else
      mv "$dst" "$dst.pre-dotclaude-$TS"
      warn "moved the existing $dst to $dst.pre-dotclaude-$TS"
    fi
  fi
  swap_tmp "$dst"
  ln -s "$src" "$SWAP_TMP"
  swap_in "$dst"
  say "linked $dst -> $src"
}

link "$REPO_DIR/tmux/tmux-claude-status" "$HOME/.local/bin/tmux-claude-status"
link "$REPO_DIR/tmux/claude-restore" "$HOME/.local/bin/claude-restore"
link "$REPO_DIR/tmux/claude-saved" "$HOME/.local/bin/claude-saved"
link "$REPO_DIR/tmux/pass-last" "$HOME/.local/bin/pass-last"
link "$REPO_DIR/tmux/paste-inbox" "$HOME/.local/bin/paste-inbox"
link "$REPO_DIR/tmux/tmux-tab-bar" "$HOME/.local/bin/tmux-tab-bar"
link "$REPO_DIR/tmux/claude-mute" "$HOME/.local/bin/claude-mute"
cheat="$HOME/.tmux-cheatsheet.txt"
if [ "$base" = 1 ]; then
  link "$REPO_DIR/tmux/cheatsheet.txt" "$cheat"
elif [ -L "$cheat" ] && [ "$(readlink "$cheat")" = "$REPO_DIR/tmux/cheatsheet.txt" ]; then
  rm "$cheat"
  say "removed $cheat"
fi

# The new ~/.tmux.conf lands with one rename too, so a tmux server starting mid-run never reads a
# missing or half-written file. A symlinked ~/.tmux.conf is written through: the temp goes beside
# the real file and replaces it, and the link stays.
python3 -I - "$HOME/.tmux.conf" "$REPO_DIR" "$base" "$TS" <<'PY'
import os, re, stat, sys, tempfile
path, repo, base, ts = sys.argv[1], sys.argv[2], sys.argv[3] == "1", sys.argv[4]
START, END = "# >>> dotclaude tmux (setup-tmux.sh) >>>", "# <<< dotclaude tmux <<<"
lines = [START]
if base:
    lines.append(f'source-file "{repo}/tmux/base.conf"')
lines += [f'source-file "{repo}/tmux/claude.conf"', END]
block = "\n".join(lines) + "\n"
old = open(path).read() if os.path.exists(path) else ""
rest = re.sub(re.escape(START) + r".*?" + re.escape(END) + r"\n?", "", old, flags=re.S)
new = (rest.rstrip("\n") + "\n\n" if rest.strip() else "") + block
if new == old:
    print(f"==> {path} already up to date")
    sys.exit(0)
if old:
    with open(f"{path}.pre-dotclaude-{ts}", "w") as f:
        f.write(old)
    print(f"==> backed up {path} to {path}.pre-dotclaude-{ts}")
real = os.path.realpath(path)
if os.path.exists(real):
    mode = stat.S_IMODE(os.stat(real).st_mode)
else:  # what a plain open() would have made
    umask = os.umask(0)
    os.umask(umask)
    mode = 0o666 & ~umask
fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(real)}.dotclaude-", dir=os.path.dirname(real))
try:
    with os.fdopen(fd, "w") as f:
        f.write(new)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, real)
except BaseException:  # a Ctrl-C too: no temp is left behind
    os.unlink(tmp)
    raise
print(f"==> wrote the dotclaude block in {path}")
PY

if tmux info >/dev/null 2>&1; then
  tmux source-file "$HOME/.tmux.conf" && say "reloaded the running tmux server"
else
  say "no tmux server running; the config loads with the next one"
fi
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) warn "$HOME/.local/bin is not on PATH; tmux calls the status script by full path, so the bar still works" ;; esac
