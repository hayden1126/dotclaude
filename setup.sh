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
# Re-running installs the baseline plus the machine overlay (backing up the old
# copy) and keeps the copy's own top-level keys; see merge-settings.py. The
# runtime re-derives its managed keys (plugins, marketplaces) on its own.
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
# What belongs to one machine (hooks for its own scripts, excludedCommands for its own
# tools) goes in settings.machine.json beside the live copy, never in this repo, and the
# copy is the baseline with that overlay merged in (merge-settings.py has the rule).
# Top-level keys only the live copy sets (autoMode, model and the other /config choices) are
# kept; a live value the baseline overrides is named on stderr. Without an overlay or such a
# key, the baseline is copied byte for byte.
MERGED_SETTINGS="$(mktemp)"
trap 'rm -f "$MERGED_SETTINGS"' EXIT
chmod 644 "$MERGED_SETTINGS"  # mktemp's 0600 would carry over to the installed copy
python3 "$REPO_DIR/merge-settings.py" "$REPO_DIR/settings.json" "$CLAUDE_DIR/settings.machine.json" \
  "$CLAUDE_DIR/settings.json" > "$MERGED_SETTINGS" \
  || { warn "settings.machine.json or the live settings.json is not valid JSON; settings.json left unchanged"; exit 1; }
copy_managed "$MERGED_SETTINGS" "$CLAUDE_DIR/settings.json"
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
  chmod +x "${d%/}"/scripts/* 2>/dev/null || true
  link "${d%/}" "$CLAUDE_DIR/skills/$(basename "$d")"
done

# agents/: per-file, because ~/.claude/agents/ also holds agents other tools install
# (the sourced framework's). Explore.md deliberately overrides the built-in Explore with
# a no-shell reader; docs/delegation.md has the reasoning.
for f in "$REPO_DIR"/agents/*.md; do
  [[ -e "$f" ]] || continue
  link "$f" "$CLAUDE_DIR/agents/$(basename "$f")"
done

# A skill that ships a CLI gets it on PATH, so the invocations printed in its
# SKILL.md and by its own tools actually resolve. Opt-in by directory: if
# ~/.local/bin does not exist, the skill still works via its absolute path.
if [[ -d "$HOME/.local/bin" ]]; then
  for exe in "$REPO_DIR"/skills/*/scripts/deckkit \
             "$REPO_DIR"/skills/delegation/scripts/{codex-delegate,delegation-ledger,gh-public}; do
    [[ -x "$exe" ]] || continue
    link "$exe" "$HOME/.local/bin/$(basename "$exe")"
  done
fi

# templates/ — per-file (SPEC/PLAN/STATUS scaffolds for full-lane work)
for f in "$REPO_DIR"/templates/*.md; do
  [[ -e "$f" ]] || continue
  link "$f" "$CLAUDE_DIR/templates/$(basename "$f")"
done

# codex/ — Codex CLI config for Codex/Claude instruction parity. AGENTS.md (the
# global working agreement) is symlinked: Codex only reads it. config.toml is NOT:
# Codex writes its own state there (a [projects."<path>"] trust entry per directory
# you trust, MCP servers other installers register), and a symlink would push that
# churn into this repo, the settings.json problem above. merge-config.py upserts the
# repo's top-level keys (the CLAUDE.md fallback and the default model) into a real ~/.codex/config.toml and
# leaves the rest alone; an old symlink becomes a local copy, so nothing is lost.
# NEVER symlink the whole ~/.codex dir: it holds auth.json (a secret) plus log/, tmp/.
CODEX_DIR="${CODEX_HOME:-$HOME/.codex}"
mkdir -p "$CODEX_DIR"
link "$REPO_DIR/codex/AGENTS.md" "$CODEX_DIR/AGENTS.md"
python3 "$REPO_DIR/codex/merge-config.py" "$REPO_DIR/codex/config.toml" "$CODEX_DIR/config.toml" \
  || warn "codex config.toml merge failed (see above); $CODEX_DIR/config.toml left unchanged"
# The skills Codex gets: the portable ones (Hayden's list, 2026-10-01). The others lean on Claude
# Code: its subagents, its own skills, chrome-devtools-mcp.
CODEX_SKILLS=(coding-practices frontend-ui-discipline research-discipline ui-alignment vetting-sources)
for s in "${CODEX_SKILLS[@]}"; do
  if [[ -d "$REPO_DIR/skills/$s" ]]; then
    link "$REPO_DIR/skills/$s" "$CODEX_DIR/skills/$s"
  else
    warn "codex skill $s is not in skills/; skipped"
  fi
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
# Two custom-command widgets live in ccstatusline's own config dir (they survive
# ccstatusline reinstalls): ctx-breakdown.py (per-category context chips, line 1)
# and session-summary.py (a 1-2 sentence session summary on lines 2-3). The
# settings baseline carries placeholder commandPaths; we patch each here with this
# machine's absolute python and script paths, because ccstatusline runs widget
# commands through the platform shell where $HOME/%USERPROFILE% expansion is not
# portable.
CC_CFG_DIR="$HOME/.config/ccstatusline"
for pyf in "$REPO_DIR"/statusline/*.py; do
  [[ -e "$pyf" ]] || continue
  link "$pyf" "$CC_CFG_DIR/$(basename "$pyf")"
done
python3 - "$REPO_DIR/statusline/ccstatusline-settings.json" "$CC_CFG_DIR/settings.json" <<'PY'
import json, os, shutil, sys, time
baseline_path, dst = sys.argv[1], sys.argv[2]
cfgdir = os.path.dirname(dst)

def patch_paths(settings):
    """Rewrite every custom-command widget whose commandPath names a bare *.py
    script to this machine's absolute python + absolute script path, preserving
    any trailing args (e.g. --row 1)."""
    for line in settings.get('lines', []):
        for w in line:
            if w.get('type') != 'custom-command':
                continue
            toks = (w.get('commandPath') or '').split()
            idx = next((i for i, t in enumerate(toks)
                        if t.strip('"').endswith('.py')), None)
            if idx is None:
                continue
            script = os.path.join(cfgdir, os.path.basename(toks[idx].strip('"')))
            rest = toks[idx + 1:]
            w['commandPath'] = ' '.join([f'"{sys.executable}"', f'"{script}"'] + rest)

def has_ctx_widget(settings):
    return any(w.get('type') == 'custom-command'
               and 'ctx-breakdown' in (w.get('commandPath') or '')
               for line in settings.get('lines', []) for w in line)

def ensure_summary_widgets(settings, baseline):
    """Idempotently ensure both session-summary rows exist. Existing installs
    already carry the ctx-breakdown widget, so the re-seed below never fires for
    them; graft the summary widgets in from the baseline instead, onto the same
    line index, preserving the user's own line-1 customizations."""
    lines = settings.setdefault('lines', [])
    while len(lines) < 3:
        lines.append([])
    def present(row):
        needle = f'--row {row}'
        return any(w.get('type') == 'custom-command'
                   and 'session-summary' in (w.get('commandPath') or '')
                   and needle in (w.get('commandPath') or '')
                   for line in lines for w in line)
    for li, bline in enumerate(baseline.get('lines', [])):
        for w in bline:
            cp = w.get('commandPath') or ''
            if w.get('type') != 'custom-command' or 'session-summary' not in cp:
                continue
            row = 1 if '--row 1' in cp else 2 if '--row 2' in cp else None
            if not row or present(row):
                continue
            ids = [int(x['id']) for l in lines for x in l
                   if str(x.get('id', '')).isdigit()]
            nw = dict(w)
            nw['id'] = str((max(ids) if ids else 0) + 1)
            while len(lines) <= li:
                lines.append([])
            lines[li].append(nw)

with open(baseline_path) as f:
    baseline = json.load(f)

settings = None
try:
    with open(dst) as f:
        settings = json.load(f)
except (OSError, ValueError):
    pass
if settings is None or not has_ctx_widget(settings):
    if settings is not None:
        backup = f'{dst}.pre-dotclaude-{int(time.time())}'
        shutil.copy(dst, backup)
        print(f'!! existing ccstatusline settings lacked the ctx widget; backed up to {backup}')
    settings = baseline

ensure_summary_widgets(settings, baseline)
patch_paths(settings)
os.makedirs(cfgdir, exist_ok=True)
with open(dst, 'w') as f:
    json.dump(settings, f, indent=2)
print('==> ccstatusline settings installed (ctx-breakdown + session-summary widgets wired)')
PY

# The sandbox block in settings.json sets failIfUnavailable: without these,
# Claude Code refuses to start. Warn now rather than at the next launch.
if [[ "$(uname -s)" == "Linux" ]]; then
  for dep in bwrap socat; do
    command -v "$dep" >/dev/null 2>&1 ||
      echo "WARNING: $dep is missing; the sandbox (failIfUnavailable) will stop Claude Code from starting. sudo apt install bubblewrap socat" >&2
  done
  # The sandbox mounts /dev/null over protected dotfiles a repo lacks, which breaks
  # `git add -A` inside it; the block (explained in the file) hides them from git.
  python3 "$REPO_DIR/git/install-ignore.py" "$REPO_DIR/git/sandbox-stubs.ignore" \
    || warn "sandbox stub block not installed into the git excludes file (see above)"
fi

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

 5.  The session-title hook (hooks/session-title.sh) needs python3 on PATH;
     if absent it fails open (leaves the title unchanged). The opt-in
     danger-guard hook (hooks/danger-guard.sh) is not wired by default; once
     you wire it, it also needs python3 and fails open (allows the command).
     The agent-spawn guard (hooks/agent-spawn-guard.sh) needs python3 too and
     FAILS CLOSED: without python3 or the linked skills/delegation it blocks
     every Agent spawn. The delegation ledger hook fails open.

 6.  The Bash sandbox is ON in settings.json, with failIfUnavailable, so Claude
     Code refuses to start without bubblewrap and socat (Linux/WSL2):
       sudo apt install bubblewrap socat
     (setup warns above if either is missing.) The seccomp filter ships inside
     the native claude binary. `claude sandbox status` prints the posture.
     The subagent policy hook (hooks/subagent-policy.sh, python3 >= 3.12)
     FAILS CLOSED for delegated agents only; the main thread never runs it.
     The report check (hooks/report-check.sh) fails open. See
     docs/delegation.md for what each layer binds.

============================================================

EOF
