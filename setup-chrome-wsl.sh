#!/usr/bin/env bash
# setup-chrome-wsl.sh — make chrome-devtools-mcp work on WSL2 (Strategy A:
# headless Linux Chrome that Claude drives itself). Opt-in and idempotent.
#
# This is intentionally NOT called by setup.sh: it is a no-op / refusal on
# non-WSL systems, where the plugin works out of the box. Run it once from a
# normal terminal (not from inside a Claude Code session). See
# docs/chrome-devtools-wsl.md for the full explanation and for Strategy B
# (attach to your real, logged-in Windows Chrome).
#
# The plugin's own server is configured through the config file it discovers
# (chrome-devtools-mcp 1.11.0 and later), so each session runs one server. The
# user-scoped `chrome-devtools` MCP entry this script used to add never shadowed
# the plugin's server: both ran in every session. Step 6 removes it.
#
# Every page tool takes a pageId, and list_pages enables Network on every open
# tab. The persistent profile restores its last session on launch and gains a
# tab per unclean shutdown (35 on HAYPC by 2026-10-04), which made list_pages
# fail with "Network.enable timed out". Step 4 clears the saved session; logins
# and cookies stay. Re-run this script if the tabs build up again.

set -euo pipefail

MIN_PLUGIN="1.11.0"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
CONFIG_DIR="$HOME/.config/cd4a"
CONFIG="$CONFIG_DIR/config.json"
PROFILE="$HOME/.cache/chrome-devtools-mcp/chrome-profile"
CHROME_DIR="$HOME/chrome"

say()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!!\033[0m  %s\n" "$*" >&2; }
die()  { printf "\033[1;31mxx\033[0m  %s\n" "$*" >&2; exit 1; }

# 0. Guards ------------------------------------------------------------------
grep -qi microsoft /proc/version 2>/dev/null \
  || die "Not WSL. chrome-devtools-mcp works out of the box on Linux/macOS; this script is WSL2-only."
command -v npx    >/dev/null || die "node/npx not found. Install Node 20+ (22 recommended) first."
command -v claude >/dev/null || die "'claude' CLI not found on PATH."
command -v python3 >/dev/null || die "python3 not found."
# The server reads $XDG_CONFIG_HOME/cd4a/config.json when that variable is set,
# and settings.json denies agents only ~/.config/cd4a. Keep the file there.
case "${XDG_CONFIG_HOME:-}" in
  ""|"$HOME/.config"|"$HOME/.config/") ;;
  *) die "XDG_CONFIG_HOME is set to $XDG_CONFIG_HOME; the server would read its config from there, outside the agents' write deny. Unset it." ;;
esac

# The installed plugin must discover its config file (added in 1.11.0).
plugin_version() {
python3 -I - "$CLAUDE_DIR/plugins/installed_plugins.json" <<'EOF'
import json, re, sys
try:
    with open(sys.argv[1]) as f:
        entries = json.load(f)["plugins"]["chrome-devtools-mcp@claude-plugins-official"]
    entry = next((e for e in entries if e.get("scope") == "user"), entries[0])
    version = entry["version"]
    if isinstance(version, str) and re.fullmatch(r"[0-9]+(\.[0-9]+)*", version):
        print(version)
except (OSError, ValueError, RecursionError, KeyError, IndexError, TypeError, AttributeError):
    pass
EOF
}
PLUGIN_VERSION="$(plugin_version)"
[ -n "$PLUGIN_VERSION" ] \
  || die "no readable chrome-devtools-mcp plugin version in $CLAUDE_DIR/plugins/installed_plugins.json; run ./setup.sh first."
[ "$(printf '%s\n%s\n' "$MIN_PLUGIN" "$PLUGIN_VERSION" | sort -V | head -1)" = "$MIN_PLUGIN" ] \
  || die "chrome-devtools-mcp plugin $PLUGIN_VERSION reads no config file; update it to $MIN_PLUGIN or later (/plugin)."

# 1. Install Chrome for Testing (no sudo) ------------------------------------
say "installing Chrome for Testing into $CHROME_DIR (no sudo)"
npx -y @puppeteer/browsers install chrome@stable --path "$CHROME_DIR" >/dev/null

# 2. Stable symlink to the newest versioned binary ---------------------------
BIN="$(ls -d "$CHROME_DIR"/chrome/linux-*/chrome-linux64/chrome 2>/dev/null | sort -V | tail -1)"
[ -x "$BIN" ] || die "Chrome binary not found under $CHROME_DIR after install."
ln -sfn "$BIN" "$CHROME_DIR/current"
say "symlink $CHROME_DIR/current -> $BIN"

# 3. Check shared libraries, then smoke-test headless ------------------------
MISSING="$(ldd "$BIN" 2>/dev/null | awk '/not found/{print $1}' | sort -u || true)"
if [ -n "$MISSING" ]; then
  warn "Chrome is missing shared libraries:"; printf '     %s\n' $MISSING >&2
  warn "Install them (needs sudo) on Debian/Ubuntu, then re-run this script:"
  warn "  sudo apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \\"
  warn "    libdrm2 libgbm1 libasound2 libxkbcommon0 libxcomposite1 libxdamage1 \\"
  warn "    libxrandr2 libxfixes3 libgtk-3-0 libpango-1.0-0"
  die "Missing libraries; see above."
fi
say "smoke test: headless load of example.com"
"$BIN" --headless --no-sandbox --disable-gpu --disable-dev-shm-usage \
  --dump-dom https://example.com 2>/dev/null | grep -q "<title>" \
  || die "Headless Chrome failed to render. Re-run the command without 2>/dev/null to see why."

# 4. Clear the profile's restored tabs (keeps logins) ------------------------
if pgrep -f -- "--user-data-dir=$PROFILE( |$)" >/dev/null; then
  warn "a Chrome is using $PROFILE; left its saved tabs alone (close Claude Code sessions, re-run)"
elif [ -d "$PROFILE/Default/Sessions" ]; then
  rm -rf "$PROFILE/Default/Sessions"
  say "cleared the restored tabs in $PROFILE"
fi

# 5. Point the plugin's server at this Chrome --------------------------------
# Merge our keys into the config file, keeping any others, then swap it in with
# one rename. The server refuses executablePath beside channel, browserUrl
# (Strategy B), wsEndpoint or autoConnect, and wsHeaders without wsEndpoint, so
# those go, with u and w (the aliases of browserUrl and wsEndpoint) and e
# (executablePath's own alias, which would override the new path).
[ -L "$CONFIG_DIR" ] || [ -L "$CONFIG" ] \
  && die "$CONFIG_DIR or its config.json is a symlink; this script writes only a real file. Remove the link and re-run."
say "writing $CONFIG"
mkdir -p "$CONFIG_DIR"
python3 -I - "$CONFIG" "$CHROME_DIR/current" <<'EOF'
import json, os, sys
path, exe = sys.argv[1], sys.argv[2]
try:
    with open(path) as f:
        config = json.load(f)
except FileNotFoundError:
    config = {}
except (ValueError, RecursionError) as err:
    sys.exit(f"xx  {path} is not valid JSON ({err}); fix or remove it, then re-run.")
if not isinstance(config, dict):
    sys.exit(f"xx  {path} is not a JSON object; fix or remove it, then re-run.")
for key in ("channel", "browserUrl", "u", "wsEndpoint", "w", "wsHeaders", "autoConnect", "e"):
    config.pop(key, None)
config.update({
    "executablePath": exe,
    "headless": True,
    "chromeArg": ["--no-sandbox", "--disable-dev-shm-usage"],
})
tmp = f"{path}.{os.getpid()}.tmp"
try:
    with open(tmp, "w") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
except BaseException:
    if os.path.exists(tmp):
        os.unlink(tmp)
    raise
EOF

# Agents must not rewrite the file, the Chrome it names or that Chrome's profile:
# all of them load outside the sandbox at session start. The denies ship in
# settings.json, live after ./setup.sh.
for rule in 'Edit(~/.config/cd4a/**)' 'Edit(~/chrome/**)' 'Edit(~/.cache/chrome-devtools-mcp/**)'; do
  if ! grep -qF "$rule" "$CLAUDE_DIR/settings.json" 2>/dev/null; then
    warn "the installed settings lack the $rule deny; run ./setup.sh so agents can't rewrite it"
  fi
done

# 6. Remove the old user-scoped override, if any -----------------------------
if claude mcp remove chrome-devtools -s user >/dev/null 2>&1; then
  say "removed the user-scoped 'chrome-devtools' MCP entry (the plugin's server replaces it)"
fi

say "done."
say "restart Claude Code, then check /mcp: one chrome-devtools server, the plugin's."
