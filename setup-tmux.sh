#!/usr/bin/env bash
# setup-tmux.sh: the tmux side of the per-window Claude indicator (◐ busy, ✳ waiting) and the
# delegation token in the status bar, and what lets a background session's hooks find its tab
# (tmux-claude-status writes that map), plus claude-restore, which reopens main's Claude tabs
# after the tmux server dies, and claude-saved, which stars and shelves a tab's chat (the
# right-click menu, Ctrl-b S). Opt-in and idempotent; setup.sh never calls it. The hook side
# (hooks/tmux-state.sh, hooks/session-registry.sh) is wired by setup.sh on every machine and does
# nothing outside tmux.
#
#   ./setup-tmux.sh           link tmux-claude-status, claude-restore and claude-saved into
#                             ~/.local/bin, source tmux/claude.conf from ~/.tmux.conf
#   ./setup-tmux.sh --base    also source tmux/base.conf (mouse, splits, the Ctrl-b Enter menu)
#                             and link the Ctrl-b h cheatsheet
#   ./setup-tmux.sh --no-base drop base.conf and the cheatsheet link
#
# The source-file lines live between markers in ~/.tmux.conf, and each run rewrites that block.
# A run with neither flag keeps base.conf as the block already has it, so a plain re-run (to link
# a new script) can't strip the mouse and menus from the next tmux server. Your own lines outside
# the block are kept; the block sits at the end, so its settings win. ~/.tmux.conf is backed up
# before any change. To remove: delete the marked block and the links (three, four with --base).

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
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
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

# Link src to dst, moving a real file at dst aside first.
link() {
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  if [ -e "$dst" ] && [ ! -L "$dst" ]; then
    mv "$dst" "$dst.pre-dotclaude-$TS"
    warn "moved the existing $dst to $dst.pre-dotclaude-$TS"
  fi
  ln -sfn "$src" "$dst"
  say "linked $dst -> $src"
}

link "$REPO_DIR/tmux/tmux-claude-status" "$HOME/.local/bin/tmux-claude-status"
link "$REPO_DIR/tmux/claude-restore" "$HOME/.local/bin/claude-restore"
link "$REPO_DIR/tmux/claude-saved" "$HOME/.local/bin/claude-saved"
cheat="$HOME/.tmux-cheatsheet.txt"
if [ "$base" = 1 ]; then
  link "$REPO_DIR/tmux/cheatsheet.txt" "$cheat"
elif [ -L "$cheat" ] && [ "$(readlink "$cheat")" = "$REPO_DIR/tmux/cheatsheet.txt" ]; then
  rm "$cheat"
  say "removed $cheat"
fi

python3 -I - "$HOME/.tmux.conf" "$REPO_DIR" "$base" "$TS" <<'PY'
import os, re, sys
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
with open(path, "w") as f:
    f.write(new)
print(f"==> wrote the dotclaude block in {path}")
PY

if tmux info >/dev/null 2>&1; then
  tmux source-file "$HOME/.tmux.conf" && say "reloaded the running tmux server"
else
  say "no tmux server running; the config loads with the next one"
fi
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) warn "$HOME/.local/bin is not on PATH; tmux calls the status script by full path, so the bar still works" ;; esac
