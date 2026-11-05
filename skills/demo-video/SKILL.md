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

Read `EVENT.md` at the project root: whether video is required, its length and format, and the judging format. If the file is missing, ask the user for the length and whether this is a submission asset, a stage backup or both. If no video is required and there is no live slot, this skill may not apply: say so, and ask before going on.

- **Submission asset:** the full script, within the required length. Set `size` in `beats.mjs` and `FPS` to the required format. For a file-size cap, re-encode the result with a higher `-crf`.
- **Stage backup:** the same path the team will show live, within the slot.
- **Fallback for one step:** in a live demo with real backends, a clip of the risky step can stand in for only that step. Record it with `BEATS=3-4`: beats 1 and 2 still run, so the app reaches the right state, and are trimmed off. It lands in `demo/out-clip/`, so give a second clip its own `OUT`. Whoever is on stage says it's a recording.

## Setup

1. Copy the template into the project, `mkdir -p demo && for f in "${CLAUDE_SKILL_DIR}"/template/*.mjs; do cat "$f" > "demo/${f##*/}"; done`, and add `demo/out*` and `demo/frames/` to `.gitignore`.
2. Install Playwright at a pinned version: `npm i -D playwright@<version>` (run `npm init -y` first if there's no `package.json`).
3. Get the browser. On an ordinary machine: `npx playwright install chromium`.
4. On a machine with a sandboxed shell and a browser cache, the browser CDN may not be allowed. Pick the Playwright version whose build is already cached: `node_modules/playwright-core/browsers.json` names the revision each version wants, and the cache folder names the ones it holds. Stay on the headless shell, the default here, since full Chrome may abort in a sandbox. A visible browser may not start inside a command sandbox either. Then the user runs that `HEADED=1` rehearsal themselves, from their own terminal. Don't ask for the sandbox to be turned off, since a take runs the app, its dependencies and the browser.
5. Check for `ffmpeg` 5.1 or later with libx264, since `-fps_mode` arrived in 5.1. On a Mac: `brew install ffmpeg`. The script checks this before it starts a take.

## Write the beats

`demo/beats.mjs` is the only file to edit. `demo/record.mjs` is the machinery. Set `app.cmd` and `app.url`, then turn the script in `DEMO.md` into beats, one caption plus one action each. If there's no `DEMO.md`, ask the user for the script. Don't invent one.

- End each action by waiting for what the viewer should see, such as `await page.getByText('Saved').waitFor()`. A wait that fails is what makes a broken take fail loud. Locators can't see the caption or the cursor, so a wait only ever matches the app.
- Make the start state repeatable. `app.cmd` should reset or seed the data, or the second take will differ from the first.
- Keep captions short enough to read in the time the beat runs. They sit at the bottom of the page, so keep important UI out from under them. A native `<dialog>` or popover draws over them and the cursor, so check those beats in the frames.

## Run it

Run `node demo/record.mjs` from the project root. Output lands in `demo/out/`: `demo.mp4`, `captions.srt` (a sidecar for players and upload forms) and `steps.json`.

| Env | Does |
|---|---|
| `APP_CMD`, `APP_URL` | Override `beats.mjs` |
| `BEATS=3-4` | A short clip of those beats, counted from 1, in `demo/out-clip/` |
| `HEADED=1` | Rehearse in a visible browser, in `demo/out-rehearsal/`. Don't ship this take. |
| `OUT` | Output dir. Wins over all of these defaults. |
| `SIZE=1280x720`, `FPS=24` | Override the format; both size numbers even |

A clip or a rehearsal never touches the full take in `demo/out/`. A good take replaces the last one in its own output dir and moves it to `demo.prev.mp4`, `captions.prev.srt` and `steps.prev.json`, one generation only, so copy a take you want to keep, or give each take its own `OUT`. A failed take leaves the last good one in place and says so.

## Believe it only after looking

An exit of 0 proves the script ran, not that the video is good.

1. Extract frames across the take, one per beat: `mkdir -p demo/frames && ffmpeg -y -v error -ss 5 -i demo/out/demo.mp4 -frames:v 1 demo/frames/5s.png`
2. Look at them at ship size, not as thumbnails. Text must be legible, captions must not cover what the beat shows, and nothing may look half loaded.
3. Run a second take with `OUT=demo/out2` and compare: `ffprobe -v error -show_entries format=duration -of csv=p=0 demo/out/demo.mp4`. Two takes should match within 2 s. A bigger gap means something in the app is racing.

**Measured on one machine:** a 119 s demo took 127 s of wall time. **Unproven:** macOS, a real app calling outside hosts through a proxy, a framework that hydrates the whole document, and audio.

## When a take fails

Read the exit message. A broken step gets fixed in the app. A step that's genuinely slow, such as a 12 s live AI call, gets its own longer wait on that one line (`waitFor({ timeout })`, for example `page.getByText('Done').waitFor({ timeout: 20000 })`), and a caption saying so or a cut in the edit, since a viewer won't sit through it in silence. The 8 s default stays for everything else. A beat that runs past 60 s in all also needs `limit: <seconds>` on that beat. A failed take makes no new video, on purpose.

| Message | Meaning |
|---|---|
| `the app exited ... before it answered` | `app.cmd` died. The app's last output is printed below the message. |
| `the app never answered` | Wrong `app.url`, or the app took over 60 s to start |
| `Timeout` on `page.goto` | The first page took over 60 s in the browser. Warm the app up in `app.cmd`, or fix what the page waits on. |
| `something already answers` | A server from another run holds the port |
| `page error`, `HTTP 5xx`, `request failed` | The app really broke during the beat named |
| `Timeout` on a selector | The thing the viewer should see never appeared, or a slow step needs its own wait |
| A browser launch error with `HEADED=1` | No visible browser can start here. The user rehearses from their own terminal. |
| `the recording stopped early` | The video came out shorter than the beats, so the recorder died partway. Run it again. |
| `a second tab opened` | Not fatal, but the video shows only the first tab. Keep the demo in one tab. |
| `warning, third-party request` | Not fatal, but look at the frames. If the demo needs that host, add it to `requiredHosts`. |

## Voiceover (optional, untested)

The template records no audio. To add a voiceover recorded to the finished take, this should work, but nobody has run it, so check the result by ear: `ffmpeg -i demo/out/demo.mp4 -i voice.m4a -map 0:v -map 1:a -c:v copy -c:a aac -shortest -movflags +faststart demo/out/demo-voice.mp4`
