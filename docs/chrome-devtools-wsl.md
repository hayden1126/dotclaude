# chrome-devtools-mcp on WSL2

The `chrome-devtools-mcp` plugin ships a server that launches its own Chrome
through Puppeteer. On WSL2 that default fails (`Protocol error ... Target
closed`): there is no Linux Chrome for it to launch, the bundled one will not
start without `--no-sandbox`, and reaching across to Windows Chrome needs
network plumbing. The fix is a machine-local, user-scoped override. It is
opt-in: `setup.sh` does not apply it, and users who are not on WSL2 need none of
this.

Two strategies. **A is the recommended default.** B is a switch for when you
need your real, logged-in Windows browser.

## Strategy A (default): native Linux Chrome, headless, autonomous

Claude drives a Chrome that lives entirely inside WSL. Nothing crosses the
WSL/Windows boundary, so it is the most reliable option and needs zero
pre-launch steps.

**Quick setup:** from a normal terminal (not inside a Claude Code session), run
the opt-in installer at the repo root:

```bash
./setup-chrome-wsl.sh
```

It is idempotent, refuses to run off WSL, and performs the three steps below,
then prints how to verify. Restart Claude Code afterward so the session loads
the override. The rest of this section explains what it does.

**Install a Linux Chrome:** Chrome for Testing under `~/chrome`, via
`npx @puppeteer/browsers install chrome@stable --path ~/chrome` (no sudo). Add a
stable symlink `~/chrome/current` pointing at the versioned binary so the config
survives version bumps.

**Register the override:** a user-scoped MCP server named `chrome-devtools` in
`~/.claude.json`, which outranks the plugin's server (user scope beats plugin
scope) while leaving the plugin's skills intact:

```bash
claude mcp add chrome-devtools --scope user -- \
  npx chrome-devtools-mcp@1.5.0 \
  --executablePath=/home/$USER/chrome/current \
  --headless \
  --chromeArg=--no-sandbox \
  --chromeArg=--disable-dev-shm-usage
```

`~/.claude.json` is runtime-owned machine state and is not tracked in this repo
(same as `known_marketplaces.json`). This doc is the reproducible record: run
the command above once per machine.

**Verify:** `claude mcp get chrome-devtools` should report `Status: ✔ Connected`.
In a session, `/mcp` lists it and a `navigate_page` + `take_screenshot` should
work with no manual setup.

**Logins:** the profile is persistent (`~/.cache/chrome-devtools-mcp/...`), so a
site you log into once stays logged in. To log in visibly, drop `--headless`
temporarily (WSLg renders the window). This browser is separate from your
Windows Chrome; none of your Windows logins or extensions carry over.

**Updating Chrome:** re-run the puppeteer install, then re-point the symlink:

```bash
npx @puppeteer/browsers install chrome@stable --path ~/chrome
ln -sfn "$(ls -d ~/chrome/chrome/linux-*/chrome-linux64/chrome | sort -V | tail -1)" ~/chrome/current
```

Prefer an auto-updating system Chrome instead? Install it once with sudo
(`google-chrome-stable`, path `/usr/bin/google-chrome`) and change
`--executablePath` to that path.

**Bumping the MCP version:** the override pins `chrome-devtools-mcp@1.5.0` for
reproducible startup. To move up, re-run `claude mcp add` (it overwrites) with a
newer version or `@latest`.

## Strategy B (switch): attach to your real Windows Chrome

Use this when a task needs your logged-in Windows session or you want to watch
the browser. This is simplest when your `.wslconfig` sets
`networkingMode=mirrored` (check: `grep networkingMode /mnt/c/Users/<you>/.wslconfig`),
so `localhost:9222` in WSL reaches Windows directly with no `netsh` port-proxy.
Without mirrored networking you would need port forwarding.

**Step 1: launch Windows Chrome with a debug port.** Run `chrome-debug.ps1`
(repo root) from Windows PowerShell. It opens Chrome on a dedicated debug
profile so it does not collide with your normal windows:

```powershell
powershell -ExecutionPolicy Bypass -File \\wsl.localhost\Ubuntu\home\<user>\dotclaude\chrome-debug.ps1
```

Make a desktop shortcut to that for one-click launching. To use your *real*
profile (real logins) instead of the debug one, fully quit Chrome first, then
pass `-UserDataDir "$env:LocalAppData\Google\Chrome\User Data"`. Chrome refuses
a debug port on a profile that is already running.

**Step 2: point the MCP at it.** Swap the server over to `--browserUrl`:

```bash
claude mcp remove chrome-devtools -s user
claude mcp add chrome-devtools --scope user -- \
  npx chrome-devtools-mcp@1.5.0 --browserUrl=http://localhost:9222
```

Restart Claude Code. The MCP now attaches to the running Windows Chrome; it will
fail if that Chrome is not up (it attaches, it cannot spawn the browser).

**Revert to A:** re-run the Strategy A `claude mcp add` command above.

## Troubleshooting

- `Target closed` / browser dies immediately: the `--chromeArg=--no-sandbox`
  flag is missing, or `--executablePath` points at a stale version path (check
  `ls -l ~/chrome/current`).
- `Status: ✗ Failed to connect` under Strategy B: the Windows Chrome is not
  running with `--remote-debugging-port=9222`, or `curl localhost:9222/json/version`
  from WSL returns nothing (mirrored networking not active).
- Confirm which server is winning: `claude mcp get chrome-devtools` shows the
  active scope and args.
