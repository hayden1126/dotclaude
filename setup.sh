#!/usr/bin/env bash
# setup.sh — install this Claude Code setup into ~/.claude
#
# Idempotent: safe to re-run. Existing files are backed up to
# ~/.claude/backups/pre-showcase-<unix-ts>/ before being replaced.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
TS="$(date +%s)"
BACKUP_DIR="$CLAUDE_DIR/backups/pre-showcase-$TS"

say()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!!\033[0m  %s\n" "$*" >&2; }
die()  { printf "\033[1;31mxx\033[0m  %s\n" "$*" >&2; exit 1; }

mkdir -p "$CLAUDE_DIR"

# ---------------------------------------------------------------------------
# 1. Back up any existing files we are about to replace
# ---------------------------------------------------------------------------
backup_if_present() {
  local target="$1"
  if [[ -e "$target" && ! -L "$target" ]]; then
    mkdir -p "$BACKUP_DIR"
    say "backing up $target -> $BACKUP_DIR/"
    mv "$target" "$BACKUP_DIR/"
  elif [[ -L "$target" ]]; then
    rm "$target"
  fi
}

# ---------------------------------------------------------------------------
# 2. Symlink the repo files into ~/.claude
# ---------------------------------------------------------------------------
link() {
  local src="$1" dst="$2"
  backup_if_present "$dst"
  mkdir -p "$(dirname "$dst")"
  ln -s "$src" "$dst"
  say "linked $dst -> $src"
}

link "$REPO_DIR/settings.json"          "$CLAUDE_DIR/settings.json"
link "$REPO_DIR/CLAUDE.md"              "$CLAUDE_DIR/CLAUDE.md"
link "$REPO_DIR/statusline-command.sh"  "$CLAUDE_DIR/statusline-command.sh"
link "$REPO_DIR/notify-toast.ps1"       "$CLAUDE_DIR/notify-toast.ps1"
chmod +x "$REPO_DIR/statusline-command.sh"

# rules/ — keep as a directory of symlinks so future additions show up
# without re-running setup
mkdir -p "$CLAUDE_DIR/rules"
for f in "$REPO_DIR"/rules/*.md; do
  [[ -e "$f" ]] || continue
  link "$f" "$CLAUDE_DIR/rules/$(basename "$f")"
done

# agents/ — same pattern (user-authored only; plugin agents come from plugins)
mkdir -p "$CLAUDE_DIR/agents"
for f in "$REPO_DIR"/agents/*.md; do
  [[ -e "$f" ]] || continue
  link "$f" "$CLAUDE_DIR/agents/$(basename "$f")"
done

# ---------------------------------------------------------------------------
# 3. Register marketplaces and install plugins
# ---------------------------------------------------------------------------
if ! command -v claude >/dev/null 2>&1; then
  warn "claude CLI not on PATH — skipping plugin install"
  warn "install Claude Code first, then re-run this script"
else
  say "registering marketplaces"
  python3 - <<'PY' "$REPO_DIR/plugins/marketplaces.json"
import json, subprocess, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
for name, entry in data.items():
    src = entry["source"]
    ref = src.get("repo") or src.get("url")
    if not ref:
        print(f"!! skipping {name}: no repo/url")
        continue
    print(f"==> claude plugin marketplace add {ref}")
    subprocess.run(["claude", "plugin", "marketplace", "add", ref], check=False)
PY

  say "installing plugins"
  python3 - <<'PY' "$REPO_DIR/plugins/enabled.json"
import json, subprocess, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
for key, enabled in data.items():
    if not enabled:
        continue
    print(f"==> claude plugin install {key}")
    subprocess.run(["claude", "plugin", "install", key], check=False)
PY
fi

# ---------------------------------------------------------------------------
# 4. Install standalone CLI tools (GSD, etc.)
# ---------------------------------------------------------------------------
say "installing standalone CLI tools from tools.json"
python3 - <<'PY' "$REPO_DIR/tools.json"
import json, subprocess, sys, shutil
with open(sys.argv[1]) as f:
    tools = json.load(f)
for name, spec in tools.items():
    installer = spec.get("installer")
    if installer == "manual":
        note = spec.get("note", "manual install required")
        print(f"!! {name}: skipped (manual). {note}")
        continue
    cmd_str = spec.get("command")
    if not cmd_str:
        print(f"!! {name}: no command, skipping")
        continue
    head = cmd_str.split()[0]
    if shutil.which(head) is None:
        print(f"!! {name}: {head!r} not on PATH, skipping")
        continue
    print(f"==> {name}: {cmd_str}")
    subprocess.run(cmd_str, shell=True, check=False)
PY

# ---------------------------------------------------------------------------
# 5. Final checklist
# ---------------------------------------------------------------------------
cat <<'EOF'

============================================================
 Setup complete. Remaining manual steps:
============================================================

 1.  Authenticate Claude Code:
       claude login

 2.  GSD was installed via `npx get-shit-done-cc` (see tools.json).
     If that step was skipped (e.g. no node on PATH), install it now:
       npx -y get-shit-done-cc
     GSD ships the hooks referenced from settings.json. If absent,
     the hooks fail open (no harm) but you lose the update banner,
     context monitor, and session-state tracking.

 3.  Re-authenticate any MCP servers (Hugging Face, Google Drive, etc.)
     from inside Claude Code with /mcp.

 4.  Windows-only: notify-toast.ps1 expects WSL. On macOS/Linux,
     replace the Notification hook in settings.json with your preferred
     notifier (osascript / notify-send / etc.).

============================================================

EOF
