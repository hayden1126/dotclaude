#!/usr/bin/env bash
# PreToolUse(Bash) hook: a command that runs outside the sandbox (one matching
# sandbox.excludedCommands) must not act on anything a sandboxed session can write. For a match it
# checks the git config the cwd resolves to, the PATH the head resolves through, and that claude
# and codex run from the project root. The rules and why are in hooks/excluded_guard.py;
# tests/setup/test_excluded_guard.py holds the cases.
#
# This shim passes the event on stdin to the module beside this script's real path, run by
# python3 -I. It FAILS CLOSED for excluded heads: if Python exits non-zero or prints output that
# isn't JSON, it denies when the command's first word (after leading whitespace and VAR=value
# words) is an excluded head, and allows anything else. Denies are logged by the module to
# $XDG_STATE_HOME/dotclaude/excluded-guard.log.
set -uo pipefail

input=$(cat)

fallback() {
    local -a words
    local re='"command"[[:space:]]*:[[:space:]]*"(([^"\\]|\\.)*)' cmd="" head="" w
    [[ $input =~ $re ]] && cmd=${BASH_REMATCH[1]}
    cmd=${cmd//\\n/ }
    cmd=${cmd//\\t/ }
    cmd=${cmd//\\r/ }
    read -r -a words <<< "$cmd"
    for w in "${words[@]}"; do
        [[ $w =~ ^[A-Za-z_][A-Za-z0-9_]*= ]] && continue
        head=${w%%[;\&|()<>]*}
        break
    done
    case $head in
        git|gh|lane|claude|codex|codex-delegate|delegation-ledger|pass-respawn|tmux|powershell.exe|cmd.exe)
            printf '{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "excluded-guard could not run, so it refuses the excluded command `%s` until it can."}}\n' "$head"
            ;;
    esac
    exit 0
}

src=$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null) || fallback
out=$(printf '%s' "$input" | python3 -I "${src%/*}/excluded_guard.py" 2>/dev/null) || fallback
[[ -z $out ]] && exit 0
printf '%s' "$out" | python3 -I -c 'import json, sys; json.loads(sys.stdin.read())' \
    >/dev/null 2>&1 || fallback
printf '%s\n' "$out"
exit 0
