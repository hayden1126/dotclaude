#!/usr/bin/env bash
# SessionStart(startup|resume|clear|compact) hook: points sandboxed Bash's package managers at
# caches of their own under ~/.cache/claude-sandbox. It appends to $CLAUDE_ENV_FILE, which Claude
# Code inlines into each Bash command, a line that exports npm_config_cache and
# BUN_INSTALL_CACHE_DIR only where the sandbox runtime set SANDBOX_RUNTIME. The sandbox then
# keeps the default caches read-only, because unsandboxed code runs from them: plugin MCP
# servers (`npx <pkg>@<version>`) from ~/.npm/_npx, which npx reuses without rechecking (gap N1),
# and bun's global installs, such as the status line's ccstatusline, as hardlinks into
# ~/.bun/install/cache (gap N3). Unsandboxed commands keep the defaults: an excluded
# `claude -p` would otherwise hand the vars to its MCP servers, and so would a settings `env`
# entry. The sandbox skips a missing allowWrite path, so the dirs are made here.
# tests/setup/test_sandbox_caches.py holds the cases.
#
# It FAILS OPEN and silent (errors go to $XDG_STATE_HOME/dotclaude/sandbox-caches.log): with no
# export, a sandboxed tool falls back to its default cache and gets a write error, so the
# sandbox still holds.
set -uo pipefail

log() {
  local d="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude"
  mkdir -p "$d" 2>/dev/null
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" 2>/dev/null >>"$d/sandbox-caches.log"
}

cat >/dev/null 2>&1
root="$HOME/.cache/claude-sandbox"
mkdir -p -m 700 "$root" 2>/dev/null
mkdir -p "$root/npm" "$root/bun" 2>/dev/null
[ -d "$root/npm" ] && [ -d "$root/bun" ] || { log "can't create the dirs under $root"; exit 0; }
[ -n "${CLAUDE_ENV_FILE:-}" ] || { log "CLAUDE_ENV_FILE is unset or empty"; exit 0; }
{
  # End another hook's unterminated last line first so ours stays whole.
  [ -s "$CLAUDE_ENV_FILE" ] && [ -n "$(tail -c1 "$CLAUDE_ENV_FILE")" ] && echo
  printf 'if [ -n "${SANDBOX_RUNTIME:-}" ]; then export npm_config_cache=%q BUN_INSTALL_CACHE_DIR=%q; fi\n' \
    "$root/npm" "$root/bun"
} 2>/dev/null >>"$CLAUDE_ENV_FILE" || log "can't write $CLAUDE_ENV_FILE"
exit 0
