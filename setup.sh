#!/usr/bin/env bash
# setup.sh — install this lean Claude Code setup into ~/.claude
#
# Idempotent: safe to re-run. Existing non-symlink files are backed up to
# ~/.claude/backups/pre-dotclaude-<unix-ts>/ before being replaced with symlinks
# back to this repo, so future edits in either place stay in sync. Each replacement
# is one rename, so an installed path doesn't go missing mid-run (section 1 names
# the cases that still remove first).
#
# It runs outside the sandbox, so every python3 it starts runs isolated (-I): no path it imports
# from comes from the cwd, the script's dir or the environment.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
TS="$(date +%s)"
BACKUP_DIR="$CLAUDE_DIR/backups/pre-dotclaude-$TS"

say()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!!\033[0m  %s\n" "$*" >&2; }

# ---------------------------------------------------------------------------
# 0. One run at a time, and a lane's install holds until the lead's
# ---------------------------------------------------------------------------
# Two runs at once would interleave their links, so a run first takes a flock on install.lock in
# the state dir. While another holds it, the run says so and waits up to 5 minutes: a sandboxed
# process can hold that lock too (a read-only fd is enough), and flock can't name the holder. A
# timeout, a lock file it can't open (a dir, another user's, a read-only file system) or any
# other flock error stops the run before it changes anything. Only where flock is missing or the
# state dir can't be made (git-bash, macOS) does the run go on unlocked. The children that may
# outlive the run (plugin installs, tool installers) get fd 9 closed, or they'd keep it.
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/dotclaude"
if command -v flock >/dev/null 2>&1 && mkdir -p "$STATE_DIR" 2>/dev/null; then
  if ! { exec 9>"$STATE_DIR/install.lock"; }; then
    warn "couldn't open $STATE_DIR/install.lock to lock it (see above); setup.sh stopped before changing anything"
    exit 1
  fi
  locked=0
  flock -n 9 || locked=$?
  if [[ $locked -eq 1 ]]; then  # flock's exit for a lock held elsewhere, and for a timeout
    say "another process holds $STATE_DIR/install.lock: this run (pid $$, from $REPO_DIR) waits up to 5 minutes for it"
    locked=0
    flock -w 300 9 || locked=$?
    if [[ $locked -eq 1 ]]; then
      warn "timed out after 5 minutes waiting for $STATE_DIR/install.lock (\`fuser -v\` on it lists who has it open); setup.sh stopped before changing anything"
      exit 1
    fi
  fi
  if [[ $locked -ne 0 ]]; then
    warn "couldn't lock $STATE_DIR/install.lock (flock exit $locked, see above); setup.sh stopped before changing anything"
    exit 1
  fi
fi
# A lane installs from its own worktree to test a change, and an install from anywhere else
# would replace those links mid-test. So links into a live lane worktree hold the install: the
# run stops here, before changing anything, unless this checkout is that lane or its main
# checkout (whose run relinks everything, releasing it). A run from a lane with no commit past
# the base (merged, or nothing committed yet) stops here too, as does one where git can't tell:
# a rerun after the lead's release would take the install back. install-state.py has the rules.
# Any other failure warns and goes on, like the lane hooks.
hold=0
python3 -I "$REPO_DIR/install-state.py" hold "$REPO_DIR" || hold=$?
if [[ $hold -eq 3 ]]; then
  warn "setup.sh stopped before changing anything"
  exit 1
elif [[ $hold -ne 0 ]]; then
  warn "the install hold check failed (exit $hold, see above); installing anyway"
fi

mkdir -p "$CLAUDE_DIR"

# ---------------------------------------------------------------------------
# 1. Symlink helpers — back up any real file we are about to replace
# ---------------------------------------------------------------------------
# An installed path is replaced, not removed and then remade: the new entry is built under a
# hidden temp name beside it (SWAP_TMP), then renamed over it in one step, so the path doesn't go
# missing (the cases that still remove first are named below). A sandboxed command that builds
# its config in such a gap sees the literal path, and on 2026-10-20 ~/.claude/CLAUDE.md vanished
# right after one. os.replace never follows the old entry, where a plain mv would drop a new
# skill link inside the old skill dir. A run that stops before the rename (an error under set -e,
# a Ctrl-C) leaves the path as the steps before it left it, and the exit trap removes the temp,
# along with section 2's merged settings: one rm, so a failure on one can't skip the other under
# set -e. rm -rf, since on git-bash, where ln -s copies, a skill's temp is a dir; it never
# follows a link.
SWAP_TMP="" MERGED_SETTINGS=""
trap 'rm -rf ${SWAP_TMP:+"$SWAP_TMP"} ${MERGED_SETTINGS:+"$MERGED_SETTINGS"}' EXIT
# Windows refuses to rename over a link to a dir (git-bash with native symlinks), so a Windows
# shell removes the old link first. The gap is back there, but no Bash sandbox runs on native
# Windows to trip on it.
case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) RENAME_OVER_LINKS=0 ;; *) RENAME_OVER_LINKS=1 ;; esac

# Point SWAP_TMP at this run's hidden temp beside $1: one dir, so the rename stays on one file
# system, and named by pid, so two runs at once (no flock on macOS or git-bash) don't share one.
# Temps beside $1 whose pid kill -0 can't signal (a run gone by a SIGKILL or a power loss, out of
# the trap's reach) are cleared, and so is one under this pid: ln and cp would follow it, and
# install-state.py would read a leftover link as a live one. A dead run's pid that another
# process has taken keeps its temp until that process ends.
swap_tmp() {
  local left
  SWAP_TMP="$(dirname "$1")/.$(basename "$1").dotclaude-$$"
  for left in "$(dirname "$1")/.$(basename "$1").dotclaude-"*; do
    kill -0 "${left##*-}" 2>/dev/null || rm -rf "$left"
  done
  rm -rf "$SWAP_TMP"
}

# Rename SWAP_TMP over $1.
swap_in() {
  if [[ $RENAME_OVER_LINKS -eq 0 && -L "$1" ]]; then rm -f "$1"; fi
  python3 -I -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' "$SWAP_TMP" "$1"
  SWAP_TMP=""
}

# A real file is copied to the backup, so it stays in place until the swap replaces it. Any other
# real entry is moved there first, leaving a gap: a dir (a hand-made one, or every skill on
# git-bash where ln -s copies), since rename can't put a link or a file over a dir, or a file cp
# can't read. A link needs nothing.
backup_if_present() {
  local target="$1" dir
  if [[ -e "$target" && ! -L "$target" ]]; then
    dir="$BACKUP_DIR$(dirname "${target#"$CLAUDE_DIR"}")"
    mkdir -p "$dir"
    say "backing up $target"
    if [[ -f "$target" && -r "$target" ]]; then
      cp -p "$target" "$dir/"
    else
      mv "$target" "$dir/"
    fi
  fi
}

link() {
  local src="$1" dst="$2"
  mkdir -p "$(dirname "$dst")"
  backup_if_present "$dst"
  swap_tmp "$dst"
  ln -s "$src" "$SWAP_TMP"
  swap_in "$dst"
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
  mkdir -p "$(dirname "$dst")"
  backup_if_present "$dst"
  swap_tmp "$dst"
  cp "$src" "$SWAP_TMP"
  swap_in "$dst"
  say "copied ${dst#"$CLAUDE_DIR/"} (runtime-managed, not symlinked)"
}

# ---------------------------------------------------------------------------
# 2. Single files
# ---------------------------------------------------------------------------
# What belongs to one machine (hooks for its own scripts, excludedCommands for its own
# tools) goes in settings.machine.json beside the live copy, never in this repo, and the
# copy is the baseline with that overlay merged in (merge-settings.py has the rule).
# Top-level keys only the live copy sets (autoMode, model and the other /config choices) are
# kept; a live value the baseline overrides is named on stderr. Installed from a checkout other
# than ~/dotclaude (a lane), that checkout's copies of the write-protected paths join denyWrite.
# Without an overlay, such a key or another checkout, the baseline is copied byte for byte.
# Before the copy replaces it: did the installed settings let the sandbox write the package
# caches, uv's Pythons or Playwright's browsers (an older dotclaude)? Then a marker in the state
# dir has section 6 point to the rebuild step on every run until Hayden removes it: the copy
# below erases the evidence, so a run stopped before section 6 must not lose the hint.
old_cache_check() {
  python3 -I - "$CLAUDE_DIR/settings.json" 2>/dev/null <<'PY' || true
import json, os, sys
try:
    allow = json.load(open(sys.argv[1]))["sandbox"]["filesystem"]["allowWrite"]
except Exception:
    sys.exit()
old = ("~/.npm", "~/.bun/install/cache", "~/.cache/uv", "~/.cache/pip", "~/.cache/pnpm", "~/.cache/node-gyp",
       "~/.cache/ms-playwright", "~/.local/share/uv", "~/.local/share/pnpm")
home = os.path.expanduser("~").rstrip("/")
for entry in (e for e in allow if isinstance(e, str) and e):
    p = entry[1:] if entry.startswith("//") else entry  # `//abs` is an absolute spelling
    p = p.rstrip("/") or "/"
    if p.startswith("/") and home.startswith(p.rstrip("/") + "/"):
        p = "~"  # a parent of home reopens every cache
    for h in (home, "$HOME"):  # an overlay may spell home out
        if h and (p == h or p.startswith(h + "/")):
            p = "~" + p[len(h):]
            break
    if any(p == o or p.startswith(o + "/") or o.startswith(p + "/") for o in old):
        # The entry itself, on one line of printable ASCII (any locale can print it, and the
        # warning's byte-wise filter keeps it whole), so the warning can name it.
        print("".join(c if " " <= c <= "~" else "?" for c in entry), end="")
        break
PY
}
old_cache_writes="$(old_cache_check)"
[[ -z $old_cache_writes ]] \
  || { mkdir -p "$STATE_DIR" && printf '%s\n' "$old_cache_writes" >"$STATE_DIR/rebuild-caches-pending"; } \
  || warn "can't write $STATE_DIR/rebuild-caches-pending: the older install's caches need a rebuild (README, \"Upgrading from an older install\")"
MERGED_SETTINGS="$(mktemp)"  # section 1's exit trap removes it
chmod 644 "$MERGED_SETTINGS"  # mktemp's 0600 would carry over to the installed copy
python3 -I "$REPO_DIR/merge-settings.py" --checkout "$REPO_DIR" "$REPO_DIR/settings.json" \
  "$CLAUDE_DIR/settings.machine.json" "$CLAUDE_DIR/settings.json" > "$MERGED_SETTINGS" \
  || { warn "settings.machine.json or the live settings.json is not valid JSON; settings.json left unchanged"; exit 1; }
copy_managed "$MERGED_SETTINGS" "$CLAUDE_DIR/settings.json"
link "$REPO_DIR/CLAUDE.md"       "$CLAUDE_DIR/CLAUDE.md"
link "$REPO_DIR/notify-toast.ps1" "$CLAUDE_DIR/notify-toast.ps1"

# hooks/ — per-file so plugin-installed hooks in ~/.claude/hooks/ are left alone. The .py
# modules beside the shims link too: where `ln -s` copies (git-bash without winsymlinks), a shim
# finds its module next to the copy.
chmod +x "$REPO_DIR"/hooks/*.sh
for f in "$REPO_DIR"/hooks/*.sh "$REPO_DIR"/hooks/*.py; do
  [[ -e "$f" ]] || continue
  link "$f" "$CLAUDE_DIR/hooks/$(basename "$f")"
done

# skills/ — one symlink per authored skill directory (plugin skills come from plugins). A
# directory holding .claude-plugin/ loads as a mod, <name>@skills-dir (skills/autopass).
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
# SKILL.md and by its own tools actually resolve; so does each standalone tool in
# bin/ (claude-file-history). Opt-in by directory: if ~/.local/bin does not exist,
# each still works via its absolute path.
if [[ -d "$HOME/.local/bin" ]]; then
  # With npm's prefix at ~/.local, ~/.local/bin/npx is npm's own: the shim would take its place
  # and find no npx behind it. So npx goes in only where nothing is, or where the shim already
  # is: a link into a checkout (bin/npx beside hooks/sandbox-caches.sh), a dangling link (a
  # closed lane's, which section 7 would prune, leaving no shim), or a copy (git-bash, where
  # ln -s copies), known by its marker line.
  npx_slot_is_ours() {
    [[ -e $1 || -L $1 ]] || return 0
    [[ -L $1 && ! -e $1 ]] && return 0
    [[ -f "$(dirname "$(readlink -f "$1")")/../hooks/sandbox-caches.sh" ]] && return 0
    grep -qF dotclaude-npx-shim "$1" 2>/dev/null
  }
  chmod +x "$REPO_DIR"/bin/* 2>/dev/null || true
  for exe in "$REPO_DIR"/bin/* "$REPO_DIR"/skills/*/scripts/deckkit \
             "$REPO_DIR"/skills/delegation/scripts/{codex-delegate,delegation-ledger,gh-public} \
             "$REPO_DIR"/skills/lanes/scripts/lane "$REPO_DIR"/skills/handoff/scripts/handoff-check \
             "$REPO_DIR"/skills/pass/scripts/pass-respawn \
             "$REPO_DIR"/skills/exam-prep/scripts/ed-pull; do
    [[ -f "$exe" && -x "$exe" ]] || continue  # a dir (bin/__pycache__) is -x too
    # Any other npx there is left alone and named; MCP launches then keep npx's project-dir
    # lookup (gap N2) until it moves.
    dst="$HOME/.local/bin/$(basename "$exe")"
    if [[ $(basename "$exe") == npx ]] && ! npx_slot_is_ours "$dst"; then
      warn "$dst isn't dotclaude's (npm's own, with npm's prefix at ~/.local?): left alone, so MCP servers still start with npx's project-dir lookup. Set npm's prefix elsewhere, then rerun setup"
      continue
    fi
    link "$exe" "$dst"
  done
  # The shim works only ahead of the real npx on PATH; a version manager (nvm, fnm, volta) or
  # Homebrew listed before ~/.local/bin wins, and MCP servers then start with npx's project-dir
  # lookup (gap N2). This run's PATH stands in for the one Claude Code inherits.
  npx_dst="$HOME/.local/bin/npx"
  if [[ -L $npx_dst && $(readlink "$npx_dst") == "$REPO_DIR/bin/npx" ]]; then
    npx_first="$(command -v npx 2>/dev/null || true)"
    [[ $npx_first -ef $npx_dst ]] \
      || warn "npx on PATH is ${npx_first:-none}, not the shim at $npx_dst: MCP servers still start with npx's project-dir lookup. Put ~/.local/bin ahead of it on PATH"
  fi
fi

# templates/ — per-file (SPEC/PLAN/STATUS/LANE scaffolds for full-track work)
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
python3 -I "$REPO_DIR/codex/merge-config.py" "$REPO_DIR/codex/config.toml" "$CODEX_DIR/config.toml" \
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
  python3 -I - "$REPO_DIR/plugins/marketplaces.json" 9>&- <<'PY'
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
  python3 -I - "$REPO_DIR/plugins/enabled.json" 9>&- <<'PY'
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
python3 -I - "$REPO_DIR/tools.json" 9>&- <<'PY'
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
# The custom-command widget ctx-breakdown.py (per-category context chips, line 1)
# lives in ccstatusline's own config dir, so it survives ccstatusline reinstalls.
# The settings baseline carries a placeholder commandPath; we patch it here with this
# machine's absolute python and script paths, because ccstatusline runs widget
# commands through the platform shell where $HOME/%USERPROFILE% expansion is not
# portable. An existing file loses the retired session-summary rows (lines 2-3).
CC_CFG_DIR="$HOME/.config/ccstatusline"
for pyf in "$REPO_DIR"/statusline/*.py; do
  [[ -e "$pyf" ]] || continue
  link "$pyf" "$CC_CFG_DIR/$(basename "$pyf")"
done
python3 -I - "$REPO_DIR/statusline/ccstatusline-settings.json" "$CC_CFG_DIR/settings.json" <<'PY'
import json, os, shutil, sys, time
baseline_path, dst = sys.argv[1], sys.argv[2]
cfgdir = os.path.dirname(dst)

def give_up(why):
    print(f"!! {dst} {why}; ccstatusline settings not installed")
    sys.exit(0)

def script_at(toks):
    """The index of the first token naming a *.py script, or None."""
    return next((i for i, t in enumerate(toks) if t.strip('"').endswith('.py')), None)

def patch_paths(settings):
    """Rewrite every custom-command widget whose commandPath names a bare *.py
    script to this machine's absolute python + absolute script path, preserving
    any trailing args."""
    for line in settings.get('lines', []):
        for w in line:
            if w.get('type') != 'custom-command':
                continue
            toks = (w.get('commandPath') or '').split()
            idx = script_at(toks)
            if idx is None:
                continue
            script = os.path.join(cfgdir, os.path.basename(toks[idx].strip('"')))
            rest = toks[idx + 1:]
            w['commandPath'] = ' '.join([f'"{sys.executable}"', f'"{script}"'] + rest)

def well_formed(settings):
    """Whether lines has the shape the helpers here read: a list of lists of widget
    objects, each commandPath a string when set."""
    lines = settings.get('lines', [])
    return isinstance(lines, list) and all(
        isinstance(line, list) and all(isinstance(w, dict)
                                       and isinstance(w.get('commandPath') or '', str)
                                       for w in line)
        for line in lines)

def has_ctx_widget(settings):
    return any(w.get('type') == 'custom-command'
               and 'ctx-breakdown' in (w.get('commandPath') or '')
               for line in settings.get('lines', []) for w in line)

def drop_retired_widgets(settings):
    """Remove the retired session-summary widgets, which earlier installs grafted onto
    lines 2-3, and each line that held nothing else. Existing installs carry the
    ctx-breakdown widget, so the re-seed below never fires for them; the user's own
    widgets and lines stay."""
    def retired(w):
        toks = (w.get('commandPath') or '').split()
        idx = script_at(toks)
        return (w.get('type') == 'custom-command' and idx is not None
                and os.path.basename(toks[idx].strip('"')) == 'session-summary.py')
    kept = []
    for line in settings.get('lines', []):
        rest = [w for w in line if not retired(w)]
        if rest or not line:
            kept.append(rest)
    settings['lines'] = kept

if os.path.lexists(dst) and not os.path.isfile(dst):
    # A directory would crash the backup copy, a FIFO would hang the read, and a
    # dangling or looping link would crash the write or send it wherever it points.
    give_up("isn't a regular file")

with open(baseline_path) as f:
    baseline = json.load(f)

settings = None
try:
    with open(dst) as f:
        settings = json.load(f)
except (OSError, ValueError, RecursionError):   # json recurses on nesting
    pass
if not isinstance(settings, dict):
    why = "isn't a readable JSON object"
elif not well_formed(settings):
    why = 'has a malformed lines list'
elif not has_ctx_widget(settings):
    why = 'lacked the ctx widget'
else:
    why = None
    try:
        json.dumps(settings, indent=2)
    except RecursionError:   # json.load reads deeper than the encoder writes
        why = 'nests too deep to write back'
if why:
    if os.path.exists(dst):
        backup = f'{dst}.pre-dotclaude-{int(time.time())}'
        try:
            shutil.copy(dst, backup)
        except OSError as e:
            give_up(f"couldn't be backed up ({e.strerror or e})")
        print(f'!! existing ccstatusline settings {why}; backed up to {backup}')
    settings = baseline

drop_retired_widgets(settings)
patch_paths(settings)
# Through a copy beside the real file, renamed over it: a write cut short leaves the
# old file whole, and ccstatusline never reads a half-written one. The copy keeps the
# file's mode, so a read-only file still refuses the write; a link stays a link.
real = os.path.realpath(dst)
new = real + '.dotclaude-new'
try:
    os.makedirs(cfgdir, exist_ok=True)
    if os.path.lexists(new):   # left by a killed run, maybe read-only
        os.unlink(new)
    if os.path.exists(real):
        shutil.copy(real, new)
    with open(new, 'w') as f:
        f.write(json.dumps(settings, indent=2))
    os.replace(new, real)
except OSError as e:
    try:
        os.unlink(new)
    except OSError:
        pass
    give_up(f"couldn't be written ({e.strerror or e})")
print('==> ccstatusline settings installed (ctx-breakdown widget wired)')
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
  python3 -I "$REPO_DIR/git/install-ignore.py" "$REPO_DIR/git/sandbox-stubs.ignore" \
    || warn "sandbox stub block not installed into the git excludes file (see above)"
fi

# ---------------------------------------------------------------------------
# 6. Copy mode for uv and pnpm installs (~/.config/uv/uv.toml, ~/.config/pnpm/rc)
# ---------------------------------------------------------------------------
# uv and pnpm hardlink a project's packages to their shared cache, so a sandboxed session working
# in a project installed outside the sandbox could edit a cache file in place through the
# project's copy, and later installs of that package anywhere would get the edit (sandbox gap
# N3). Copy mode gives each project files of its own. A project's own setting beats the user
# file, but a project that sets it controls its install anyway (its scripts, its build backend).
# A value the file already sets stays, named on stderr. bun has no such setting, only
# `bun install --backend=copyfile`. Copy mode covers new installs only: the run that first sets
# it points to bin/cache-unlink, which finds and un-links the installs made before, unless a
# rebuild is pending (the rebuild replaces those installs).

# Put LINE at the top of FILE (above any [table], where a TOML key would belong to the table)
# unless the top level already sets KEY. Written in place, so a linked file stays a link. A
# table that sets KEY to another value (uv's [pip]) is named, and kept. A file it can't read or
# write is named and skipped, so the rest of setup still runs. Sets copy_mode_new on a write.
copy_mode_new=""
set_top_key() {
  local file="$1" key="$2" line="$3" want="$4" sets top="" t rest target
  if [[ ! -e $file && ! -L $file ]]; then
    if mkdir -p "$(dirname "$file")" && printf '%s\n' "$line" > "$file"; then
      say "set $key in $file"
      copy_mode_new=1
    else
      warn "can't create $file: $key not set"
    fi
    return
  fi
  [[ -f $file && -r $file && -w $file ]] || { warn "can't read or write $file: $key not set"; return; }
  # One line per place that sets KEY: "=value" at the top level, "table=value" in a table. A
  # quoted key counts, and a trailing comment is not part of the value.
  sets="$(awk -v k="$key" '
    /^[[:space:]]*\[/ { t = $0; sub(/^[[:space:]]*\[+[[:space:]]*/, "", t); sub(/[[:space:]]*\].*$/, "", t); next }
    {
      l = $0; sub(/^[[:space:]]+/, "", l); q = substr(l, 1, 1)
      if (q == "\"" || q == "'\''") {
        if (substr(l, length(k) + 2, 1) != q) next
        l = substr(l, 2, length(k)) substr(l, length(k) + 3)
      }
      if (index(l, k) != 1 || substr(l, length(k) + 1) !~ /^[[:space:]]*=/) next
      v = substr(l, length(k) + 1); sub(/^[[:space:]]*=[[:space:]]*/, "", v)
      sub(/[[:space:]]*[#;].*$/, "", v); gsub(/["'\''[:space:]]/, "", v)
      print t "=" v
    }' "$file")"
  while IFS= read -r t; do
    if [[ $t == =* ]]; then
      [[ -n $top ]] || top="${t#=}"
    elif [[ -n $t && ${t#*=} != "$want" ]]; then
      warn "$file sets $key to ${t#*=} in [${t%%=*}], kept: those installs can hardlink to the shared cache"
    fi
  done <<<"$sets"
  if [[ -n $top ]]; then
    [[ $top == "$want" ]] \
      || warn "$file sets $key to $top, kept: installs there can hardlink to the shared cache"
    return
  fi
  # Written to a copy beside the real file (cp -p keeps its mode), then renamed over it: a
  # failed write (disk full) leaves the old file whole, and a link stays a link.
  # The newline goes on in its own step: bash versions differ on $'\n' inside "${v:+...}".
  rest="$(cat "$file")"
  [[ -z $rest ]] || rest+=$'\n'
  target="$(readlink -f "$file")"
  if cp -p "$target" "$target.setup.$$" \
     && printf '%s\n%s' "$line" "$rest" > "$target.setup.$$" \
     && mv -f "$target.setup.$$" "$target"; then
    say "set $key in $file"
    copy_mode_new=1
  else
    rm -f "$target.setup.$$"
    warn "can't write $file: $key not set"
  fi
}

# Windows (git-bash) has no Bash sandbox to write a project, so copy mode buys nothing there (and
# its config dirs are APPDATA's, not these).
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) say "copy mode skipped: no Bash sandbox on Windows" ;;
  *)
    config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
    set_top_key "$config_home/uv/uv.toml" link-mode 'link-mode = "copy"' copy
    # pnpm's global rc is in XDG_CONFIG_HOME when that is set, else ~/Library/Preferences on
    # macOS and ~/.config elsewhere.
    pnpm_dir="$config_home/pnpm"
    [[ -z ${XDG_CONFIG_HOME:-} && $(uname -s) == Darwin ]] && pnpm_dir="$HOME/Library/Preferences/pnpm"
    set_top_key "$pnpm_dir/rc" package-import-method package-import-method=copy copy
    # Then ask pnpm itself, from /, so no project's .npmrc counts: a ~/.npmrc or an OS path this
    # missed would show here. COREPACK_ENABLE_NETWORK=0 stops a corepack pnpm downloading one.
    if command -v pnpm >/dev/null 2>&1; then
      pnpm_import="$(cd / && COREPACK_ENABLE_NETWORK=0 pnpm config get package-import-method \
        </dev/null 2>/dev/null)" || pnpm_import=""
      [[ -z $pnpm_import || $pnpm_import == copy ]] \
        || warn "pnpm reads package-import-method as $pnpm_import, not copy (set in ~/.npmrc, or a config dir this missed): its installs can hardlink to the shared cache"
    fi
    # Section 2's marker, from the settings a run replaced. While it stands, the rebuild replaces
    # every project env (fresh installs, in copy mode), so the cache-unlink hint would only
    # send the user to a tool first.
    rebuild_marker="${STATE_DIR:-}/rebuild-caches-pending"
    if [[ -n ${STATE_DIR:-} && -e $rebuild_marker ]]; then
      rebuild_entry="$(head -c 300 "$rebuild_marker" | head -n 1 | tr -cd '[:print:]')" || rebuild_entry=""
      warn "an older install let the sandbox write the package caches, uv's Pythons or Playwright's browsers${rebuild_entry:+ (allowWrite entry $rebuild_entry; if settings.machine.json has it, remove it there)}, and unsandboxed runs still use them: rebuild them once (README, \"Upgrading from an older install\"), rerun ./setup.sh, then rm $rebuild_marker"
    elif [[ -n $copy_mode_new ]]; then
      warn "copy mode is new here: uv and pnpm installs made before it still share files with their caches. List them with \`cache-unlink <your project dirs>\`, then rerun it with --apply"
    fi
    ;;
esac

# ---------------------------------------------------------------------------
# 7. Stale links and plugin changes
# ---------------------------------------------------------------------------
# After the last link: remove the managed links this run didn't replace that point into another
# live lane worktree (a file only that lane has), and the dangling ones into this checkout or
# the lanes root (a removed hook, a closed lane). setup-tmux.sh's links and plugin files are
# left alone; install-state.py has the rule.
python3 -I "$REPO_DIR/install-state.py" prune "$REPO_DIR" \
  || warn "pruning stale links failed (see above); they are left in place"
# A running session loads plugins and mods only at its start (SKILL.md text it picks up live),
# so name each one that changed since the last install: those sessions need /pass to see it.
python3 -I "$REPO_DIR/install-state.py" plugins \
  || warn "the plugin change check failed (see above)"
# The excluded-command guard refuses an excluded call that would act on something a sandboxed
# session can write. Name each repo under ~ and each PATH dir it would refuse now (a new tool's
# bin dir, a repo whose install step points core.hooksPath into it), what each holds, and the
# settings.machine.json with the Edit deny rules that clear them.
python3 -I "$REPO_DIR/hooks/excluded_guard.py" --scan \
  || warn "the excluded-command guard would refuse the calls above: look at each dir, fix each as the scan says (most by pasting the settings.machine.json it printed), and rerun setup where its last line says"

# ---------------------------------------------------------------------------
# 8. Final checklist
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
     sounds come from hooks/stop-ring.sh and hooks/notify.sh, only for a session
     you see (hooks/session-pane.sh); the toast goes through hooks/notify.sh
     (WSL via wslpath, native Windows via cygpath) and renders notify-toast.ps1.
     On macOS/Linux, swap them for your platform's notifier (osascript /
     notify-send). For the tmux window indicator, run ./setup-tmux.sh once.

 5.  The session-title hook (hooks/session-title.sh) needs python3 on PATH;
     if absent it fails open (leaves the title unchanged).
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
     docs/delegation.md for what each layer binds. The overwrite guard
     (hooks/overwrite-guard.sh), the delete guard (hooks/delete-guard.sh)
     and the ask check (hooks/ask-check.sh) need python3 and fail open;
     memory-git.sh needs git and never blocks. The practices check
     (hooks/practices-check.sh) needs python3 >= 3.11 (tomllib) and fails
     open but loud: session start reports its errors.
     The excluded-command guard (hooks/excluded-guard.sh) needs python3 and
     FAILS CLOSED for excluded commands: without it, git push, gh, lane,
     claude and the other excluded heads are refused. Setup ends with its
     scan (hooks/excluded_guard.py --scan): rerun it after adding a PATH dir
     or cloning a repo with in-repo git hooks.
     The lane hooks (hooks/lane-identity.sh, hooks/lane-guard.sh) need
     python3 >= 3.11 (tomllib) and fail open; see docs/lanes.md.

============================================================

EOF
