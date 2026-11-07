---
name: demo-video
description: Record the product's scripted demo video once it is frozen. One command starts the app, drives it with human pacing, records and encodes. It makes the submission asset and the backup for a live demo, never the live demo itself.
argument-hint: "[what the demo shows]"
disable-model-invocation: true
---

# Demo video

Request from the user: $ARGUMENTS

A scripted take of the real app: captions, a visible cursor, H.264, by default at 1920x1080 and a constant 30 fps. Make it calmly, **only once the product is frozen**, since a changed screen means a new take.

It is a submission asset, a backup if the live demo fails on stage, or both. It is not the live demo: there the team runs the actual product, which `/pitch` covers when the user types it. If that skill isn't here, the rule stands. Keep the two apart.

## Fit it to the event

Read `EVENT.md` at the project root: whether video is required, its length and format, and the judging format. If the file is missing, ask the user for the length, whether this is a submission asset, a stage backup or both, and whether the event's rules limit work or tools from before the start, or require third-party material to be disclosed. If no video is required and there is no live slot, this skill may not apply: say so, and ask before going on.

- **Submission asset:** the full script, within the required length. Set `size` and `fps` in `beats.mjs` to the required format, so every retake keeps it. For a file-size cap, re-encode the result with a higher `-crf`.
- **Stage backup:** the same path the team will show live, within the slot.
- **Fallback for one step:** in a live demo with real backends, a clip of the risky step can stand in for only that step. Record it with `BEATS=3-4`: beats 1 and 2 still run, so the app reaches the right state, and are trimmed off. It lands in `demo/out-clip/`, so give a second clip its own `OUT`. Whoever is on stage says it's a recording.

## Setup

1. Copy the template into the project, which keeps any beats already written: `mkdir -p demo && cat "${CLAUDE_SKILL_DIR}/template/record.mjs" > demo/record.mjs && { [ -e demo/beats.mjs ] || cat "${CLAUDE_SKILL_DIR}/template/beats.mjs" > demo/beats.mjs; }`. Add `demo/` to `.gitignore`. The product repo holds the product, and the recorder isn't part of it: it's tooling from before the event, MIT licensed as part of dotclaude. Declare it instead: say in the README that the video is a scripted Playwright recording. Read `EVENT.md`'s "Work allowed before the start" and "Third-party material" fields: disclose the recorder the way they ask, and if they forbid tools from before the event, tell the user before recording. Commit `demo/` only when the event's submission rules want assets rebuildable from the repo or the user asks; then replace the `demo/` line in `.gitignore` with `demo/out*`, `demo/frames/` and `demo/node_modules/`, and tell the user the recorder is MIT licensed as part of dotclaude, so that licence text goes with the copy.
2. Install Playwright at a pinned version inside `demo/`, so the product's own `package.json` never gains it: `( cd demo && { [ -e package.json ] || npm init -y >/dev/null; } && npm i -D playwright@<version> )`. The parentheses keep the session in the project root. Without `demo/package.json`, npm would install into the product's own. `record.mjs` finds it in `demo/`. On a machine with a sandboxed shell, pick `<version>` by step 4 first.
3. Get the browser. On an ordinary machine: `( cd demo && npx playwright install chromium )`.
4. On a machine with a sandboxed shell and a browser cache, the browser CDN may not be allowed. Pick the Playwright version whose build is already cached. The cache folder (`$PLAYWRIGHT_BROWSERS_PATH` if set, otherwise `~/.cache/ms-playwright` on Linux and `~/Library/Caches/ms-playwright` on macOS) names the builds it holds, and this reads the build a version wants without installing it: `curl -sL "$(npm view playwright-core@<version> dist.tarball)" | tar -xzO -f - package/browsers.json`. After the install, `demo/node_modules/playwright-core/browsers.json` confirms it. Stay on the headless shell, the default here, since full Chrome may abort in a sandbox. A visible browser may not start inside a command sandbox either. Then the user runs that `HEADED=1` rehearsal themselves, from their own terminal. Ask in chat first, and say what that means: the app, every package it loads and the beats you wrote run with no sandbox, with reach to their files and network. A visible browser needs the full `chromium` build, which a cache holding only the headless shell lacks: they run `( cd demo && npx playwright install chromium )` there first. Don't ask for the sandbox to be turned off: that would cover every later command of the session, while the user's terminal covers one run they approved.
5. Check for `ffmpeg` 5.1 or later with libx264, since `-fps_mode` arrived in 5.1. On a Mac: `brew install ffmpeg`. The script checks this before it starts a take.

## Write the beats

`demo/beats.mjs` is the only file to edit. `demo/record.mjs` is the machinery. Set `app.cmd` and `app.url`. For an app already running elsewhere (deployed, on a board or a LAN address), set `app.cmd` to `''`: the take neither starts nor stops it, and the start state is yours to reset. Only the browser reaches it. A sandboxed shell has its own network, so an app in another terminal on this machine isn't reachable: start it through `app.cmd` instead. A remote or LAN host must be on the project's allowed list in `.claude/settings.local.json` (an IP address there is untested), and so must every outside host the page loads, images included. When a host is missing, ask the user to add it, add a row for it to `ACCESS.md` if that file exists, and rerun. Don't get past a missing host by handing the take to the user's terminal: the host stays missing for the app and every later command. When a host on the list still fails, read which side failed. `request failed: <url> (net::ERR_TUNNEL_CONNECTION_FAILED)` is the browser: check the host's spelling in the list, that it's in `.claude/settings.local.json`, and whether the URL redirects to another host. `HTTP 5xx` on the app's own URL, with a connection error in the app's output, is the app's server ignoring the proxy settings (Node's `fetch` needs `NODE_USE_ENV_PROXY=1`, from Node 24): fix that inside the sandbox. If the take still fails, tell the user, and offer no route around the sandbox. Export `ignoreHTTPSErrors = true` for a self-signed certificate. Then turn the script in `DEMO.md` into beats, one caption plus one action each. If there's no `DEMO.md`, ask the user for the script. Don't invent one.

- End each action by waiting for what the viewer should see, such as `await page.getByText('Saved').waitFor()`. A wait that fails is what makes a broken take fail loud. Locators can't see the caption or the cursor, so a wait only ever matches the app.
- Make the start state repeatable. `app.cmd` should reset or seed the data, or the second take will differ from the first.
- If the user runs the app's dev server from this folder, ask them to stop it before a take: the take starts its own copy, and the two share the data files and the build folder, so the take's reset would wipe what theirs holds.
- Keep captions short enough to read in the time the beat runs. They sit at the bottom of the page, so keep important UI out from under them. A native `<dialog>` or popover draws over them and the cursor, so check those beats in the frames.

## Run it

Run `node demo/record.mjs` from the project root. Output lands in `demo/out/`: `demo.mp4`, `captions.srt` (a sidecar for players and upload forms) and `steps.json`.

| Env | Does |
|---|---|
| `APP_CMD`, `APP_URL` | Override `beats.mjs` |
| `BEATS=3-4` | A short clip of those beats, counted from 1, in `demo/out-clip/` |
| `HEADED=1` | Rehearse in a visible browser, in `demo/out-rehearsal/`. Don't ship this take. |
| `OUT` | Output dir. Wins over all of these defaults. |
| `SIZE=1280x720`, `FPS=24` | Override `beats.mjs` for one take; both size numbers even |

A clip or a rehearsal never touches the full take in `demo/out/`. A good take replaces the last one in its own output dir and moves it to `demo.prev.mp4`, `captions.prev.srt` and `steps.prev.json`, one generation only, so copy a take you want to keep, or give each take its own `OUT`. A failed take leaves the last good one in place and says so.

## Believe it only after looking

An exit of 0 proves the script ran, not that the video is good.

1. Extract frames across the take, one per beat: `mkdir -p demo/frames && ffmpeg -y -v error -ss 5 -i demo/out/demo.mp4 -frames:v 1 demo/frames/5s.png`
2. Look at them at ship size, not as thumbnails. Text must be legible, captions must not cover what the beat shows, and nothing may look half loaded.
3. Run a second take with `OUT=demo/out2` and compare: `ffprobe -v error -show_entries format=duration -of csv=p=0 demo/out/demo.mp4`. Two takes should match within 2 s. A bigger gap means something in the app is racing.

**Measured on one machine:** a 119 s demo took 127 s of wall time. **Measured in a command sandbox:** the browser reaches an allowed outside host through the proxy variables, and a host not allowed fails loud with `net::ERR_TUNNEL_CONNECTION_FAILED`. **Unproven:** macOS, a framework that hydrates the whole document, audio, and an app's own server calling outside hosts from a sandbox, which depends on whether its HTTP client honours those variables (Node's `fetch` needs `NODE_USE_ENV_PROXY=1`, from Node 24).

## When a take fails

Read the exit message. A broken step gets fixed in the app. A step that's genuinely slow, such as a 12 s live AI call, gets its own longer wait on that one line (`waitFor({ timeout })`, for example `page.getByText('Done').waitFor({ timeout: 20000 })`), and a caption saying so or a cut in the edit, since a viewer won't sit through it in silence. The 8 s default stays for everything else. A beat that runs past 60 s in all also needs `limit: <seconds>` on that beat. A failed take makes no new video, on purpose.

| Message | Meaning |
|---|---|
| `the app exited ... before it answered` | `app.cmd` died. The app's last output is printed below the message. |
| `the app never answered` | Wrong `app.url`, or the app took over 60 s to start, or `app.url` keeps answering with an error |
| `net::ERR_` on `page.goto` | The browser can't reach `app.url`. In a sandboxed shell, `ERR_TUNNEL_CONNECTION_FAILED` means the host isn't on the allowed list. |
| `Timeout` on `page.goto` | The first page took over 60 s in the browser. Warm the app up in `app.cmd`, or fix what the page waits on. |
| `something already answers` | A server from another run holds the port. If it's the user's dev server, ask them to stop it, so the take starts its own copy with a fresh start state. Set `app.cmd` to `''` only for an app that can't be started here. |
| `page error`, `HTTP 5xx`, `request failed` | The app really broke during the beat named |
| `Timeout` on a selector | The thing the viewer should see never appeared, or a slow step needs its own wait |
| A browser launch error with `HEADED=1` | No visible browser can start here. The user may rehearse from their own terminal, after the ask in Setup step 4. |
| `the recording stopped early` | The video came out shorter than the beats, so the recorder died partway. Run it again. |
| `a second tab opened` | Not fatal, but the video shows only the first tab. Keep the demo in one tab. |
| `warning, third-party request` | Not fatal, but look at the frames: a blank image is often a host missing from the allowed list. If the demo needs that host, ask the user to allow it, and add it to `requiredHosts` so a later take fails loud. |

## Voiceover (optional, untested)

The template records no audio. To add a voiceover recorded to the finished take, this should work, but nobody has run it, so check the result by ear: `ffmpeg -i demo/out/demo.mp4 -i voice.m4a -map 0:v -map 1:a -c:v copy -c:a aac -shortest -movflags +faststart demo/out/demo-voice.mp4`
