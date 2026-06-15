#!/usr/bin/env bash
# sync.sh — refresh the repo's derived plugin lists from live ~/.claude/ state.
#
# Regenerates:
#   plugins/marketplaces.json  <- ~/.claude/plugins/known_marketplaces.json
#   plugins/enabled.json       <- ~/.claude/settings.json::enabledPlugins
#
# Everything else (settings.json, CLAUDE.md, skills/, hooks/, templates/,
# notify-toast.ps1) is symlinked by setup.sh, so the repo IS the live copy —
# no sync needed. Safe to re-run; reports a diff but never auto-commits.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

say() { printf "\033[1;36m==>\033[0m %s\n" "$*"; }

say "syncing plugins/marketplaces.json"
python3 - "$CLAUDE_DIR/plugins/known_marketplaces.json" "$REPO_DIR/plugins/marketplaces.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    data = json.load(f)
out = {name: {"source": entry["source"]} for name, entry in data.items()}
with open(dst, "w") as f:
    json.dump(out, f, indent=2, sort_keys=True)
    f.write("\n")
PY

say "syncing plugins/enabled.json"
python3 - "$CLAUDE_DIR/settings.json" "$REPO_DIR/plugins/enabled.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    settings = json.load(f)
with open(dst, "w") as f:
    json.dump(settings.get("enabledPlugins", {}), f, indent=2, sort_keys=True)
    f.write("\n")
PY

if command -v git >/dev/null 2>&1 && [[ -d "$REPO_DIR/.git" ]]; then
  cd "$REPO_DIR"
  if ! git diff --quiet -- plugins/; then
    say "changes detected:"
    git diff --stat -- plugins/
    say "review: git -C $REPO_DIR diff plugins/"
    say "commit when ready: git -C $REPO_DIR add -A && git -C $REPO_DIR commit -m 'sync plugins from ~/.claude/'"
  else
    say "no changes — repo already in sync"
  fi
fi
