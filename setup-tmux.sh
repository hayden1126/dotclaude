#!/usr/bin/env bash
# setup-tmux.sh: the tmux side of the per-window Claude indicator (◐ busy, ✳ waiting) and the
# delegation token in the status bar, and what lets a background session's hooks find its tab
# (tmux-claude-status writes that map), plus claude-restore, which reopens main's Claude tabs
# after a reboot. Opt-in and idempotent; setup.sh never calls it. The hook side
# (hooks/tmux-state.sh, hooks/session-registry.sh) is wired by setup.sh on every machine and does
# nothing outside tmux.
#
#   ./setup-tmux.sh           link tmux-claude-status and claude-restore into ~/.local/bin,
#                             source tmux/claude.conf from ~/.tmux.conf
#   ./setup-tmux.sh --base    also source tmux/base.conf (mouse, splits, the Ctrl-b Enter menu)
#                             and link the Ctrl-b h cheatsheet
#
# The source-file lines live between markers in ~/.tmux.conf, and each run rewrites that block to
# match its flags (a run without --base drops base.conf). Your own lines outside it are kept;
# the block sits at the end, so its settings win. ~/.tmux.conf is backed up before any change.
# To remove: delete the marked block and the links (two, three with --base).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
TS="$(date +%Y%m%d-%H%M%S)"

say()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!!\033[0m  %s\n" "$*" >&2; }
die()  { printf "\033[1;31mxx\033[0m  %s\n" "$*" >&2; exit 1; }

base=0
for arg in "$@"; do
  case "$arg" in
    --base) base=1 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) die "unknown argument: $arg (try --help)" ;;
  esac
done

command -v tmux >/dev/null || die "tmux not found. Install it first (sudo apt install tmux)."
command -v python3 >/dev/null || die "python3 not found."

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
[ "$base" = 1 ] && link "$REPO_DIR/tmux/cheatsheet.txt" "$HOME/.tmux-cheatsheet.txt"

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
