#!/usr/bin/env bash
# setup.sh — install this lean Claude Code setup into ~/.claude
#
# Idempotent: safe to re-run. Existing non-symlink files are backed up to
# ~/.claude/backups/pre-dotclaude-<unix-ts>/ before being replaced with symlinks
# back to this repo, so future edits in either place stay in sync.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
TS="$(date +%s)"
BACKUP_DIR="$CLAUDE_DIR/backups/pre-dotclaude-$TS"

say()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!!\033[0m  %s\n" "$*" >&2; }

mkdir -p "$CLAUDE_DIR"

# ---------------------------------------------------------------------------
# 1. Symlink helpers — back up any real file we are about to replace
# ---------------------------------------------------------------------------
backup_if_present() {
  local target="$1"
  if [[ -e "$target" && ! -L "$target" ]]; then
    mkdir -p "$BACKUP_DIR$(dirname "${target#"$CLAUDE_DIR"}")"
    say "backing up $target"
    mv "$target" "$BACKUP_DIR$(dirname "${target#"$CLAUDE_DIR"}")/"
  elif [[ -L "$target" ]]; then
    rm "$target"
  fi
}

link() {
  local src="$1" dst="$2"
  backup_if_present "$dst"
  mkdir -p "$(dirname "$dst")"
  ln -s "$src" "$dst"
  say "linked ${dst#"$CLAUDE_DIR/"} -> repo"
}

# settings.json is the one file the runtime itself rewrites (it persists managed
# keys like extraKnownMarketplaces and reorders the file). A live symlink would
# push that churn straight back into the repo, so we COPY it instead: the repo
# file is the curated baseline; the runtime owns its own copy in ~/.claude/.
# Re-running resets the copy to the baseline (backing up the old one); the
# runtime then re-derives its managed keys on next launch.
copy_managed() {
  local src="$1" dst="$2"
  if [[ -e "$dst" && ! -L "$dst" ]] && cmp -s "$src" "$dst"; then
    say "${dst#"$CLAUDE_DIR/"} already current"; return
  fi
  backup_if_present "$dst"
  mkdir -p "$(dirname "$dst")"
  cp "$src" "$dst"
  say "copied ${dst#"$CLAUDE_DIR/"} (runtime-managed, not symlinked)"
}

# ---------------------------------------------------------------------------
# 2. Single files
# ---------------------------------------------------------------------------
copy_managed "$REPO_DIR/settings.json" "$CLAUDE_DIR/settings.json"
link "$REPO_DIR/CLAUDE.md"       "$CLAUDE_DIR/CLAUDE.md"
link "$REPO_DIR/notify-toast.ps1" "$CLAUDE_DIR/notify-toast.ps1"

# hooks/ — per-file so plugin-installed hooks in ~/.claude/hooks/ are left alone
chmod +x "$REPO_DIR"/hooks/*.sh
for f in "$REPO_DIR"/hooks/*.sh; do
  [[ -e "$f" ]] || continue
  link "$f" "$CLAUDE_DIR/hooks/$(basename "$f")"
done

# skills/ — one symlink per authored skill directory (plugin skills come from plugins)
for d in "$REPO_DIR"/skills/*/; do
  [[ -d "$d" ]] || continue
  link "${d%/}" "$CLAUDE_DIR/skills/$(basename "$d")"
done

# templates/ — per-file (SPEC/PLAN/STATUS scaffolds for full-lane work)
for f in "$REPO_DIR"/templates/*.md; do
  [[ -e "$f" ]] || continue
  link "$f" "$CLAUDE_DIR/templates/$(basename "$f")"
done

# ---------------------------------------------------------------------------
# 3. Register marketplaces and install plugins
# ---------------------------------------------------------------------------
if ! command -v claude >/dev/null 2>&1; then
  warn "claude CLI not on PATH — skipping plugin install (install Claude Code, then re-run)"
else
  say "registering marketplaces"
  python3 - "$REPO_DIR/plugins/marketplaces.json" <<'PY'
import json, subprocess, sys
with open(sys.argv[1]) as f:
    data = json.load(f)
for name, entry in data.items():
    src = entry["source"]
    ref = src.get("repo") or src.get("url")
    if not ref:
        print(f"!! skipping {name}: no repo/url"); continue
    print(f"==> claude plugin marketplace add {ref}")
    subprocess.run(["claude", "plugin", "marketplace", "add", ref], check=False)
PY

  say "installing plugins"
  python3 - "$REPO_DIR/plugins/enabled.json" <<'PY'
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
# 4. Standalone CLI tools (ccstatusline, etc.)
# ---------------------------------------------------------------------------
say "installing standalone CLI tools from tools.json"
python3 - "$REPO_DIR/tools.json" <<'PY'
import json, subprocess, sys, shutil
with open(sys.argv[1]) as f:
    tools = json.load(f)
for name, spec in tools.items():
    if spec.get("installer") == "manual":
        print(f"!! {name}: skipped (manual). {spec.get('note','manual install required')}"); continue
    cmd_str = spec.get("command")
    if not cmd_str:
        print(f"!! {name}: no command, skipping"); continue
    head = cmd_str.split()[0]
    if shutil.which(head) is None:
        print(f"!! {name}: {head!r} not on PATH, skipping"); continue
    print(f"==> {name}: {cmd_str}")
    subprocess.run(cmd_str, shell=True, check=False)
PY

# ---------------------------------------------------------------------------
# 5. Status line widget (~/.config/ccstatusline)
# ---------------------------------------------------------------------------
# ctx-breakdown.py renders per-category context chips in the status line. It
# lives in ccstatusline's own config dir (survives ccstatusline reinstalls).
# The settings baseline carries a placeholder commandPath; we patch it here
# with this machine's absolute python and script paths, because ccstatusline
# executes widget commands through the platform shell where $HOME/%USERPROFILE%
# expansion is not portable.
CC_CFG_DIR="$HOME/.config/ccstatusline"
link "$REPO_DIR/statusline/ctx-breakdown.py" "$CC_CFG_DIR/ctx-breakdown.py"
python3 - "$REPO_DIR/statusline/ccstatusline-settings.json" "$CC_CFG_DIR/settings.json" <<'PY'
import json, os, shutil, sys, time
baseline_path, dst = sys.argv[1], sys.argv[2]
script = os.path.join(os.path.dirname(dst), 'ctx-breakdown.py')
cmd = f'"{sys.executable}" "{script}"'

def has_widget(settings):
    return any(w.get('type') == 'custom-command'
               and 'ctx-breakdown' in (w.get('commandPath') or '')
               for line in settings.get('lines', []) for w in line)

settings = None
try:
    with open(dst) as f:
        settings = json.load(f)
except (OSError, ValueError):
    pass
if settings is None or not has_widget(settings):
    if settings is not None:
        backup = f'{dst}.pre-dotclaude-{int(time.time())}'
        shutil.copy(dst, backup)
        print(f'!! existing ccstatusline settings lacked the widget; backed up to {backup}')
    with open(baseline_path) as f:
        settings = json.load(f)
for line in settings.get('lines', []):
    for w in line:
        if w.get('type') == 'custom-command' and 'ctx-breakdown' in (w.get('commandPath') or ''):
            w['commandPath'] = cmd
os.makedirs(os.path.dirname(dst), exist_ok=True)
with open(dst, 'w') as f:
    json.dump(settings, f, indent=2)
print('==> ccstatusline settings installed (ctx-breakdown widget wired)')
PY

# ---------------------------------------------------------------------------
# 6. Final checklist
# ---------------------------------------------------------------------------
cat <<'EOF'

============================================================
 Setup complete. Remaining manual steps:
============================================================

 1.  Authenticate Claude Code:
       claude login

 2.  Status line uses ccstatusline (installed via bun from tools.json).
     If bun was not on PATH, install bun then run:
       bun install -g ccstatusline
     The context chips widget needs one /context run per session to pick
     up the category split; until then it shows the total with a hint.

 3.  Re-authenticate any MCP servers (context7, chrome-devtools) from
     inside Claude Code with /mcp.

 4.  Windows/WSL only: the Stop + Notification hooks call powershell.exe. The
     sound hooks are inline in settings.json; the toast goes through
     hooks/notify.sh (WSL via wslpath, native Windows via cygpath) and renders
     notify-toast.ps1. On macOS/Linux, swap them for your platform's notifier
     (osascript / notify-send).

 5.  The danger-guard hook (hooks/danger-guard.sh) needs python3 on PATH.
     If absent it fails open (allows the command, no guard).

============================================================

EOF
