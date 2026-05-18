#!/usr/bin/env bash
# sync.sh — refresh the dotclaude repo from the live ~/.claude/ state.
#
# Regenerates:
#   plugins/marketplaces.json  <- ~/.claude/plugins/known_marketplaces.json
#   plugins/enabled.json       <- ~/.claude/settings.json::enabledPlugins
#   agents/*.md                <- non-plugin user-authored agents in ~/.claude/agents/
#
# settings.json, CLAUDE.md, rules/, statusline-command.sh, and notify-toast.ps1
# are managed via symlink (see setup.sh), so they are already live — no sync needed.
#
# Safe to re-run. Diffs against git after sync; if changes exist, prints a summary
# but does NOT auto-commit (you decide what's worth tracking).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

say() { printf "\033[1;36m==>\033[0m %s\n" "$*"; }

# ---------------------------------------------------------------------------
# 1. plugins/marketplaces.json — strip volatile fields (installLocation, lastUpdated)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# 2. plugins/enabled.json — pull from settings.json::enabledPlugins
# ---------------------------------------------------------------------------
say "syncing plugins/enabled.json"
python3 - "$CLAUDE_DIR/settings.json" "$REPO_DIR/plugins/enabled.json" <<'PY'
import json, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src) as f:
    settings = json.load(f)
enabled = settings.get("enabledPlugins", {})
with open(dst, "w") as f:
    json.dump(enabled, f, indent=2, sort_keys=True)
    f.write("\n")
PY

# ---------------------------------------------------------------------------
# 3. agents/ — copy user-authored agents (those NOT shipped by any plugin)
# ---------------------------------------------------------------------------
say "syncing agents/ (user-authored only)"
python3 - "$CLAUDE_DIR" "$REPO_DIR/agents" <<'PY'
import os, shutil, sys, glob
claude_dir, repo_agents = sys.argv[1], sys.argv[2]
src_agents = os.path.join(claude_dir, "agents")
plugin_cache = os.path.join(claude_dir, "plugins", "cache")

# Build set of plugin-shipped agent basenames
plugin_owned = set()
for depth in ("*/*/*/agents/*.md", "*/*/*/*/agents/*.md"):
    for p in glob.glob(os.path.join(plugin_cache, depth)):
        plugin_owned.add(os.path.basename(p))

# GSD installs its agents directly into ~/.claude/agents/ via this manifest
import json as _json
manifest_path = os.path.join(claude_dir, "gsd-file-manifest.json")
if os.path.exists(manifest_path):
    with open(manifest_path) as f:
        manifest = _json.load(f)
    for path in manifest.get("files", {}):
        if path.startswith("agents/") and path.endswith(".md"):
            plugin_owned.add(os.path.basename(path))

live_names = set()
for src in glob.glob(os.path.join(src_agents, "*.md")):
    name = os.path.basename(src)
    if name in plugin_owned:
        continue
    live_names.add(name)
    dst = os.path.join(repo_agents, name)
    shutil.copyfile(src, dst)
    print(f"  + {name}")

for existing in glob.glob(os.path.join(repo_agents, "*.md")):
    if os.path.basename(existing) not in live_names:
        print(f"  - {os.path.basename(existing)} (no longer in ~/.claude/agents/)")
        os.remove(existing)
PY

# ---------------------------------------------------------------------------
# 4. Report
# ---------------------------------------------------------------------------
if command -v git >/dev/null 2>&1 && [[ -d "$REPO_DIR/.git" ]]; then
  cd "$REPO_DIR"
  if ! git diff --quiet -- plugins/ agents/; then
    say "changes detected:"
    git diff --stat -- plugins/ agents/
    say "review with: git -C $REPO_DIR diff plugins/ agents/"
    say "commit when ready: git -C $REPO_DIR add -A && git -C $REPO_DIR commit -m 'sync from ~/.claude/'"
  else
    say "no changes — repo already in sync"
  fi
fi
