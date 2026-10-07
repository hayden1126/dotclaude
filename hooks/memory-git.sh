#!/usr/bin/env bash
# SessionStart and Stop hook: commits every project's auto-memory to a local-only git repo, so a
# memory file overwritten or deleted by any means (a Bash heredoc included) can be restored.
# Claude Code's file-history already backs up tool writes, but only for about 30 days and never
# for Bash; this is the long-lived backstop for memory (docs/blind-overwrite-brief.md).
#
#   git dir    $XDG_STATE_HOME/dotclaude/memory.git (mode 700, no remote: memory is private)
#   work tree  ${CLAUDE_CONFIG_DIR:-~/.claude}/projects, tracking only */memory/**; the git dir's
#              info/exclude ignores everything else, so transcripts are never walked or added.
#
# Read it back with:
#   git --git-dir="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude/memory.git" log --stat
#
# Several sessions run at once: a live index.lock means another one is committing, so this exits
# quietly and the next trigger commits. A lock older than a minute was left by a killed run and
# is removed. Never blocks: always exits 0. tests/setup/test_memory_git.py holds the cases.
set -uo pipefail

input=$(cat 2>/dev/null)
root="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"
gd="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude/memory.git"
[ -d "$root" ] || exit 0
umask 077

g() {
  git -c core.hooksPath=/dev/null -c commit.gpgsign=false -c user.name=memory-git \
    -c user.email=memory-git@localhost --git-dir="$gd" --work-tree="$root" "$@"
}

if [ ! -f "$gd/HEAD" ]; then
  mkdir -p "$gd" && g init -q 2>/dev/null || exit 0
  printf '%s\n' '/*' '!/*/' '/*/*' '!/*/memory/' > "$gd/info/exclude" 2>/dev/null || exit 0
fi

lock="$gd/index.lock"
if [ -e "$lock" ]; then
  [ -n "$(find "$lock" -mmin +1 2>/dev/null)" ] || exit 0
  rm -f "$lock"
fi

field() { printf '%s' "$input" | grep -o "\"$1\": *\"[^\"]*\"" | head -n 1 | sed 's/.*"\([^"]*\)"$/\1/'; }
event=$(field hook_event_name)
sid=$(field session_id)

g add -A -- ':(glob)*/memory/**' 2>/dev/null || exit 0
g diff --cached --quiet 2>/dev/null && exit 0
g commit -q -m "${event:-hook} ${sid:0:8}" 2>/dev/null
exit 0
