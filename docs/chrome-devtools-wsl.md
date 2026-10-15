# chrome-devtools-mcp on WSL2

The `chrome-devtools-mcp` plugin ships a server that launches its own Chrome
through Puppeteer. On WSL2 that default fails (`Protocol error ... Target
closed`): there is no Linux Chrome for it to launch, the bundled one will not
start without `--no-sandbox`, and reaching across to Windows Chrome needs
network plumbing. The fix is a machine-local, user-scoped override. It is
opt-in: `setup.sh` does not apply it, and users who are not on WSL2 need none of
this.

Two strategies. **A is the recommended default.** B is a switch for when you
need your real, logged-in Windows browser. Separately, `chrome-bg` runs Windows
Chrome behind all your windows for headed puppeteer probes (see
[Background Windows Chrome for probes](#background-windows-chrome-for-probes-chrome-bg)).

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
  npx chrome-devtools-mcp@1.9.0 \
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

**Bumping the MCP version:** the override pins `chrome-devtools-mcp@1.9.0` for
reproducible startup. To move up, re-run `claude mcp add` (it overwrites) with a
newer version or `@latest`.

**Restored tabs:** the persistent profile reopens its last session on launch and
gains a tab each time Chrome exits uncleanly. 1.9.0 enables Network on every tab
for `list_pages`, so a few dozen dead tabs time it out (`Network.enable timed
out`). `setup-chrome-wsl.sh` clears `Default/Sessions` in the profile, which
drops the tabs and keeps logins; re-run it if the error comes back.

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
  npx chrome-devtools-mcp@1.9.0 --browserUrl=http://localhost:9222
```

Restart Claude Code. The MCP now attaches to the running Windows Chrome; it will
fail if that Chrome is not up (it attaches, it cannot spawn the browser).

**Revert to A:** re-run the Strategy A `claude mcp add` command above.

## Background Windows Chrome for probes (chrome-bg)

Strategies A and B serve the MCP. `bin/chrome-bg` serves a headed puppeteer
probe or fixture of your own. A Chrome window opened from WSL normally comes to
the front and keeps the foreground, so your keystrokes land in it. chrome-bg
runs Windows Chrome so that its window never takes the foreground and never
shows on top: it sits behind all your windows, a normal window you can still
switch to, and a page covered by other windows keeps rendering.

**Requirements:**

- WSL2 with mirrored networking (see Strategy B): the fixture reaches Chrome at
  `http://127.0.0.1:<port>` on the Windows side.
- Run `chrome-bg` and the fixture with the sandbox off. `powershell.exe` and
  Chrome's port are unreachable inside it, and chrome-bg refuses to start there
  (exit 2).
- Serve the pages under test over http from WSL, sandbox-off as well (the
  sandbox has its own network namespace). Windows Chrome can't read
  `file:///home/...`, while `http://localhost:<port>` served from WSL works.

**The fixture:** connect when chrome-bg handed you a URL, launch otherwise, and
drive the page chrome-bg already placed:

```js
const browser = process.env.CHROME_BG_URL
  ? await puppeteer.connect({ browserURL: process.env.CHROME_BG_URL, defaultViewport: null })
  : await puppeteer.launch({ headless: false });
const page = (await browser.pages())[0];
```

Page 0 is the window chrome-bg opened in the background and sank to the bottom.
A fresh `newPage()` opens a foreground tab, which activates its window. The
WMI launch below kept that from raising anything in the probes, but page 0
doesn't depend on it. `defaultViewport: null` lets the page take the window's
size (`--size`) rather than puppeteer's 800x600. Calling `browser.close()` at
the end is fine: chrome-bg treats a Chrome that is already gone as stopped.

**The CLI:**

```
chrome-bg run [--url U] [--size WxH] [--env NAME] -- CMD...
chrome-bg start [--url U] [--size WxH] [--ttl 2h] [--json]
chrome-bg stop <id|url>
chrome-bg stop --gc
chrome-bg ls
chrome-bg check
```

- `run` starts Chrome, runs CMD with the browserURL in `$NAME` (default
  `CHROME_BG_URL`), and stops Chrome when CMD ends. It exits with CMD's code
  (128 plus the signal when CMD dies by one, 127 when CMD can't start). TERM,
  HUP and ctrl-c reach CMD, and Chrome stops after it. `--url` sets the first
  page (default `about:blank`), `--size` the window in DIPs (default
  `1280x900`).
- `start` makes a detached run and prints its browserURL, or
  `{id, url, port, pid}` with `--json`. A holder process owns the run until
  `stop`, `--ttl` (default `2h`; takes `90s`, `30m`, `2h` or `1d`), or Chrome
  exiting (a fixture's `browser.close()`, or you closing the window). Use it
  when a probe spans several commands:
  `export CHROME_BG_URL=$(chrome-bg start)`.
- `stop <id|url>` stops one run by its id or browserURL, never by a bare port
  (see the cleanup rule below).
- `stop --gc` stops runs whose owner is gone or whose TTL ran out, kills run
  dirs that no record claims once they are 2 minutes old (a younger one may be
  a run still launching), and prunes logs older than 7 days. Every `start` and
  `run` does this first.
- `ls` lists runs: id, port, Chrome pids, owner, age, cwd. A run dir with no
  record shows as `no record`.
- `check` is the live self-test. It opens a window behind yours for about 30 s,
  takes each action a fixture might (a default `newPage`, `bringToFront`,
  maximize and restore, `window.open`), then judges the supervisor's log. It
  passes when no run window took the foreground or sat above another window,
  the covered page stayed `visible` and drew frames within 10% of the
  monitor's rate, and nothing was left after stop. Exit 0 is a pass, 1 a fail,
  3 inconclusive. Inconclusive means the window in front at the start was not a
  visible one, so a steal can't be told from Windows handing over a dead
  foreground: put one of your windows in front and rerun.

**How it works:** each run gets an 8-hex id, a fresh profile in its own run
dir, and Chrome on `--remote-debugging-port=0`. Its flags are puppeteer's
launch defaults less `--disable-popup-blocking`, which would let a
gestureless `window.open` put a popup on screen. One supervisor per run,
`chrome-bg.ps1` (Windows PowerShell, found beside `bin/chrome-bg`'s real
path), does the Windows half. The rules, and why:

- **Chrome launches through WMI, never `Start-Process`.** Started by the
  console-attached supervisor, Chrome inherited the console's right to take
  the foreground. On its first `newPage()` it took the foreground from the
  terminal and held it for about 45 s. Launched through WMI
  (`Win32_Process.Create`), it took the foreground in none of 21 actions.
- **The window starts off-screen, in the background.** The first window opens
  over CDP with `background: true`, left of every monitor. The supervisor then
  moves it onto the primary monitor at the bottom of the z-order without
  activating it (`SetWindowPos(HWND_BOTTOM, SWP_NOACTIVATE)`).
- **Each new frame sinks at creation.** Off-screen bounds alone still left the
  first window on top of the screen for 7-9 ms before they applied: too short
  for a 50 ms poll to catch, long enough to see. So the supervisor sinks every
  new run frame to the bottom at `EVENT_OBJECT_CREATE`, while it is still
  hidden.
- **The supervisor writes stdout only in reply.** It takes one JSON command per
  stdin line and answers each with one line; window events go to its log. A
  stray stdout write after its owner died killed the supervisor and left 8
  chrome.exe running. `bin/chrome-bg` also starts it with SIGPIPE ignored and
  in a session of its own: a reply still in flight when the owner is killed
  then can't take the WSL relay down, and a ctrl-c in the terminal can't reach
  it. Only its stdin closing ends it, and it cleans up first. If it exits any
  other way, or reports an incomplete cleanup (exit 3), `bin/chrome-bg` kills
  the run by its dir itself.
- **Cleanup goes by run dir, never by port.** A chrome.exe belongs to a run
  when its command line holds `\chrome-bg\<id>\`. Chrome may relaunch itself
  and its children outlive their parent, so a recorded pid isn't proof, while
  the run dir is unique to the run. A port isn't proof either: 9222
  may be `chrome-debug.ps1` with your real profile, and a start refuses a port
  whose `/json/version` names another browser. When the run's owner (`run`, or
  the `start` holder) exits, cleanly or killed, the supervisor's stdin closes,
  and it kills the run's chrome.exe and deletes the dir.
- **The keeper is a backstop.** While no run window has the foreground, the
  supervisor sinks any run window it sees above another on-screen window, at
  most 20 times per window per second. Under the WMI launch it had nothing to
  do. It stands down while a run window has the foreground, so a window you
  clicked stays up.
- **A covered page still renders.** `--disable-backgrounding-occluded-windows`
  plus `CalculateNativeWinOcclusion` in the disabled features keep the page
  `visible`, at the monitor's frame rate, behind other windows. The flag alone
  sufficed in the probes; the feature entry is a second guard.
- **Window titles are logged only for run windows.** The log records which
  window holds the foreground and where run windows rank, so your windows show
  up in it, but by class and pid only. A log you share carries none of your
  terminal or session titles.

**Where things live:**

- Records of live runs: `$XDG_STATE_HOME/dotclaude/chrome-bg/<id>.json`
  (default `~/.local/state`), with each `start` holder's log beside them.
- On Windows, under `%TEMP%\chrome-bg\`: the run dir `<id>\` (the profile is in
  `<id>\profile`), deleted at stop, and the supervisor's log `<id>.log`. The
  log outlives the run, for `check` and post-mortems; gc prunes logs after 7
  days.
- One WSL distro per Windows user: gc takes every run dir under
  `%TEMP%\chrome-bg\` that no local record claims as its own, so a second distro
  running chrome-bg would have its runs killed after 2 minutes.

**Keep Bash off the display (`hooks/blank-display.sh`):** in a repo whose
fixtures launch a headed browser, a fixture run from Bash with `DISPLAY` set
opens a WSLg window in front of you. This SessionStart hook takes the display
away from Bash in a repo that opts in:

```bash
git config dotclaude.blankDisplay true      # opt in
git config --unset dotclaude.blankDisplay   # opt out
```

The hook reads the key with `--local`. In a linked worktree that reads the
common dir's config, so every worktree of the repo is covered, including ones
added later. Global and system config never opt a repo in.

Opted in, the hook appends three lines to `CLAUDE_ENV_FILE`, which Claude Code
sources before each Bash command:

```bash
export DISPLAY=
export WAYLAND_DISPLAY=
unset WAYLAND_SOCKET
```

The two vars are set empty rather than unset, since an unset var can fall back
to the default sockets (`/tmp/.X11-unix/X0`, `$XDG_RUNTIME_DIR/wayland-0`). The
hook also tells the model why, and to use `chrome-bg run` sandbox-off for a
visible browser. It is never a settings `env` entry: Claude Code's own image
paste runs `xclip` and `wl-paste` with that env, so paste would break. Errors
go to `$XDG_STATE_HOME/dotclaude/blank-display.log`, and the hook fails open.

## Troubleshooting

- `Target closed` / browser dies immediately: the `--chromeArg=--no-sandbox`
  flag is missing, or `--executablePath` points at a stale version path (check
  `ls -l ~/chrome/current`).
- `Status: ✗ Failed to connect` under Strategy B: the Windows Chrome is not
  running with `--remote-debugging-port=9222`, or `curl localhost:9222/json/version`
  from WSL returns nothing (mirrored networking not active).
- Confirm which server is winning: `claude mcp get chrome-devtools` shows the
  active scope and args.
