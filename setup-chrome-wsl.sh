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
#   CDT_VERSION=1.5.0 ./setup-chrome-wsl.sh    # override the pinned MCP version

set -euo pipefail

CDT_VERSION="${CDT_VERSION:-1.5.0}"
CHROME_DIR="$HOME/chrome"

say()  { printf "\033[1;36m==>\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!!\033[0m  %s\n" "$*" >&2; }
die()  { printf "\033[1;31mxx\033[0m  %s\n" "$*" >&2; exit 1; }

# 0. Guards ------------------------------------------------------------------
grep -qi microsoft /proc/version 2>/dev/null \
  || die "Not WSL. chrome-devtools-mcp works out of the box on Linux/macOS; this script is WSL2-only."
command -v npx    >/dev/null || die "node/npx not found. Install Node 20+ (22 recommended) first."
command -v claude >/dev/null || die "'claude' CLI not found on PATH."

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

# 4. Register the user-scoped override (idempotent: remove, then add) --------
say "registering user-scoped 'chrome-devtools' override (pinned @$CDT_VERSION)"
claude mcp remove chrome-devtools -s user >/dev/null 2>&1 || true
claude mcp add chrome-devtools --scope user -- \
  npx "chrome-devtools-mcp@$CDT_VERSION" \
  "--executablePath=$CHROME_DIR/current" \
  --headless \
  --chromeArg=--no-sandbox \
  --chromeArg=--disable-dev-shm-usage

say "done."
say "verify:  claude mcp get chrome-devtools    (expect: Status: Connected)"
say "then restart Claude Code so the session loads it, and check /mcp."
