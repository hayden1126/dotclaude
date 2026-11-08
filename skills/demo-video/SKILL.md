---
name: demo-video
description: Use when the user asks to record, make, redo, voice or caption a demo video of their app, such as a hackathon submission video or a recorded backup for a live demo, or to edit one in invideo. One command starts the app, drives it with human pacing, records and encodes; then a recorded voice, subtitles, labels and note boxes go on. Not for a live demo, a pitch, or writing a demo script or DEMO.md.
argument-hint: "[what the demo shows]"
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

1. Copy the template into the project, which keeps any beats already written: `mkdir -p demo && cat "${CLAUDE_SKILL_DIR}/template/record.mjs" > demo/record.mjs && cat "${CLAUDE_SKILL_DIR}/template/voice.mjs" > demo/voice.mjs && cat "${CLAUDE_SKILL_DIR}/template/captions.mjs" > demo/captions.mjs && { [ -e demo/beats.mjs ] || cat "${CLAUDE_SKILL_DIR}/template/beats.mjs" > demo/beats.mjs; }`. Add `demo/` to `.gitignore`. The product repo holds the product, and the recorder isn't part of it: it's tooling from before the event, MIT licensed as part of dotclaude. Declare it instead: say in the README that the video is a scripted Playwright recording. Read `EVENT.md`'s "Work allowed before the start" and "Third-party material" fields: disclose the recorder the way they ask, and if they forbid tools from before the event, tell the user before recording. Commit `demo/` only when the event's submission rules want assets rebuildable from the repo or the user asks; then replace the `demo/` line in `.gitignore` with `demo/out*`, `demo/frames/`, `demo/voice*/` and `demo/node_modules/`, and tell the user the recorder is MIT licensed as part of dotclaude, with its licence text at the top of `record.mjs`, `voice.mjs` and `captions.mjs`, which has to stay there.
2. Install Playwright at a pinned version inside `demo/`, so the product's own `package.json` never gains it: `( cd demo && { [ -e package.json ] || npm init -y >/dev/null; } && npm i -D playwright@<version> )`. The parentheses keep the session in the project root. Without `demo/package.json`, npm would install into the product's own. `record.mjs` finds it in `demo/`. On a machine with a sandboxed shell, pick `<version>` by step 4 first.
3. Get the browser. On an ordinary machine: `( cd demo && npx playwright install chromium )`.
4. On a machine with a sandboxed shell and a browser cache, the browser CDN may not be allowed. Pick the Playwright version whose build is already cached. The cache folder (`$PLAYWRIGHT_BROWSERS_PATH` if set, otherwise `~/.cache/ms-playwright` on Linux and `~/Library/Caches/ms-playwright` on macOS) names the builds it holds, and this reads the build a version wants without installing it: `curl -sL "$(npm view playwright-core@<version> dist.tarball)" | tar -xzO -f - package/browsers.json`. After the install, `demo/node_modules/playwright-core/browsers.json` confirms it. Stay on the headless shell, the default here, since full Chrome may abort in a sandbox. A visible browser may not start inside a command sandbox either. Then the user runs that `HEADED=1` rehearsal themselves, from their own terminal. Ask in chat first, and say what that means: the app, every package it loads and the beats you wrote run with no sandbox, with reach to their files and network. A visible browser needs the full `chromium` build, which a cache holding only the headless shell lacks: they run `( cd demo && npx playwright install chromium )` there first. Don't ask for the sandbox to be turned off: that would cover every later command of the session, while the user's terminal covers one run they approved.
5. Check for `ffmpeg` 5.1 or later with libx264, since `-fps_mode` arrived in 5.1. The script checks this before it starts a take. Captions also need libass: `ffmpeg -hide_banner -filters | grep -w ass` prints a line when it's there. On a Mac, Homebrew's plain `ffmpeg` has no libass (checked 2026-11-08), so `brew install ffmpeg-full`, which installs off the PATH: put `"$(brew --prefix ffmpeg-full)/bin"` first on it.

## Write the beats

`demo/beats.mjs` is the only file to edit. `demo/record.mjs` is the machinery. Set `app.cmd` and `app.url`. For an app already running elsewhere (deployed, on a board or a LAN address), set `app.cmd` to `''`: the take neither starts nor stops it, and the start state is yours to reset. Only the browser reaches it. A sandboxed shell has its own network, so an app in another terminal on this machine isn't reachable: start it through `app.cmd` instead. A remote or LAN host must be on the project's allowed list in `.claude/settings.local.json` (an IP address there is untested), and so must every outside host the page loads, images included. When a host is missing, ask the user to add it, add a row for it to `ACCESS.md` if that file exists, and rerun. Don't get past a missing host by handing the take to the user's terminal: the host stays missing for the app and every later command. When a host on the list still fails, read which side failed. `request failed: <url> (net::ERR_TUNNEL_CONNECTION_FAILED)` is the browser: check the host's spelling in the list, that it's in `.claude/settings.local.json`, and whether the URL redirects to another host. `HTTP 5xx` on the app's own URL, with a connection error in the app's output, is the app's server ignoring the proxy settings (Node's `fetch` needs `NODE_USE_ENV_PROXY=1`, from Node 24): fix that inside the sandbox. If the take still fails, tell the user, and offer no route around the sandbox. Export `ignoreHTTPSErrors = true` for a self-signed certificate. Then turn the script in `DEMO.md` into beats, one caption plus one action each.

**Check the script first.** Before writing a beat, read `DEMO.md` and take the first row that fits. "Moved" means `git diff --stat <hash> HEAD` (the hash from the `Checked before recording:` line) or `git status --short` lists anything beyond `demo/`, `DEMO.md`, `.gitignore`, the README, `EVENT.md`, `PITCH.md`, `ACCESS.md`, `CLAUDE.md`, `VISION.md`, and empty stub files a command sandbox puts at the repo root.

| `DEMO.md` now | Do |
|---|---|
| No script at all | Ask the user for the script, or to type `/demo-first-scope`, write what they give into `DEMO.md`, and take the table again. Don't invent one. |
| The user said to skip this check, for a reason they gave | Write the beats, and note the reason in `DEMO.md`. |
| A script, but a beat has neither a said line nor a silent mark | Stop, and ask the user to type `/demo-first-scope before recording`, or to say why not. Don't write the lines yourself. |
| A script, but no audience and coverage section (who judges, and what the demo must cover, each item mapped to a beat or a written field, or marked dropped) | The same stop. |
| A script, but no `Checked before recording:` line | The same stop. |
| Every piece is there, but the product moved | The same stop. |
| Every piece is there, and the product hasn't moved | Write the beats. |

If `/demo-first-scope` isn't installed, ask the user who judges, what the demo must cover, and any missing said lines, commit any product changes with their OK, write the answers and a line `Checked before recording: <date and time>, at commit <hash>`, replacing any earlier one, into `DEMO.md`, with the hash from `git rev-parse --short HEAD`, and take the table again.

- End each action by waiting for what the viewer should see, such as `await page.getByText('Saved').waitFor()`. A wait that fails is what makes a broken take fail loud. Locators can't see the caption or the cursor, so a wait only ever matches the app.
- Make the start state repeatable. `app.cmd` should reset or seed the data, or the second take will differ from the first.
- If the user runs the app's dev server from this folder, ask them to stop it before a take: the take starts its own copy, and the two share the data files and the build folder, so the take's reset would wipe what theirs holds.
- Keep captions short enough to read in the time the beat runs. With `labels = 'after'` (see Captions) they become labels at the top of the finished video, and with `'page'` they sit at the bottom of the page: keep important UI out from under them either way. A native `<dialog>` or popover draws over them and the cursor, so check those beats in the frames.

## Run it

Run `node demo/record.mjs` from the project root. Output lands in `demo/out/`: `demo.mp4`, `captions.srt` (the labels as the take recorded them) and `steps.json`. A voiceover, if you add one, goes beside them as `demo-voice.mp4`. The captioned video goes there too, as `demo-captioned.mp4`, with `subtitles.srt`, which holds the spoken lines and is the sidecar for players and upload forms.

| Env | Does |
|---|---|
| `APP_CMD`, `APP_URL` | Override `beats.mjs` |
| `BEATS=3-4` | A short clip of those beats, counted from 1, in `demo/out-clip/` |
| `HEADED=1` | Rehearse in a visible browser, in `demo/out-rehearsal/`. Don't ship this take. |
| `OUT` | Output dir. Wins over all of these defaults. |
| `SIZE=1280x720`, `FPS=24` | Override `beats.mjs` for one take; both size numbers even |

A clip or a rehearsal never touches the full take in `demo/out/`. A good take replaces the last one in its own output dir and moves it to `demo.prev.mp4`, `captions.prev.srt` and `steps.prev.json`, one generation only, so copy a take you want to keep, or give each take its own `OUT`. It also moves a `demo-voice.mp4` made for the old take to `demo-voice.prev.mp4`, and a `demo-captioned.mp4` and `subtitles.srt` made from it to `demo-captioned.prev.mp4` and `subtitles.prev.srt`, replacing the ones there, with a warning to run `voice.mjs` and `captions.mjs` again. A failed take leaves the last good one in place and says so.

## Believe it only after looking

An exit of 0 proves the script ran, not that the video is good.

1. Extract frames across the take, one per beat: `mkdir -p demo/frames && ffmpeg -y -v error -ss 5 -i demo/out/demo.mp4 -frames:v 1 demo/frames/5s.png`
2. Look at them at ship size, not as thumbnails. Text must be legible, captions must not cover what the beat shows, and nothing may look half loaded.
3. Run a second take with `OUT=demo/out2` and compare: `ffprobe -v error -show_entries format=duration -of csv=p=0 demo/out/demo.mp4`. Two takes should match within 2 s. A bigger gap means something in the app is racing.

**Measured on one machine:** a 119 s demo took 127 s of wall time. **Measured in a command sandbox:** the browser reaches an allowed outside host through the proxy variables, and a host not allowed fails loud with `net::ERR_TUNNEL_CONNECTION_FAILED`. **Measured under WSLg:** a USB microphone set as the Windows default input records through `RDPSource` from the user's own prompt. Inside a command sandbox, ffmpeg's `pulse` input fails with `socket(): Operation not permitted`. **Unproven:** macOS, a framework that hydrates the whole document, and an app's own server calling outside hosts from a sandbox, which depends on whether its HTTP client honours those variables (Node's `fetch` needs `NODE_USE_ENV_PROXY=1`, from Node 24).

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

## Voiceover (optional)

A take has no sound. The voice goes on afterwards, so a fluffed line never costs a new take. Make it only from a take you've looked at, since a new take moves `demo-voice.mp4` aside and the voice has to be built again.

`node demo/voice.mjs cues` lists each part to record: the whole read, and each beat with its time, length and caption, each with how many seconds to record. `node demo/captions.mjs lines` is the sheet to read the words from, once the beats have `say` lines (see Captions): run it yourself and paste it into the chat for the speaker. Read from those, with the silent `demo.mp4` playing in front of the speaker so the words keep pace with the picture. When pace matters, offer clips per beat first: each one starts on its beat, so a slow line can't push the rest late, as it can in one continuous read. Record with any app, in any format ffmpeg reads, then add each recording with `node demo/voice.mjs add <all or N> <file>`. It checks the file, names it, and puts it in `demo/voice/`, keeping that part's last file hidden beside it:

| File | Does |
|---|---|
| `all.<ext>` | A continuous read, started on the first caption |
| `<N>.<ext>` | A clip for beat N, counted in this take, which starts on that beat |
| both | The clip replaces the read across beat N, which is how one part of a read is redone |

Silence and room noise before the first word and after the last are dropped, so a late start costs nothing. A longer sound before the first word or after the last, such as a rustle, someone talking nearby or reaching to stop the recorder, counts as speech: listen, and trim it in an editor or record that part again. Then `node demo/voice.mjs` builds `demo/out/demo-voice.mp4`: the take's picture, copied untouched, with the voice at the take's exact length. For a clip take, set `OUT` to its dir: its voice files then go in the matching dir, `demo/voice-clip/` for `demo/out-clip/`, since beat numbers count within one take. `VOICE` names another voice dir, so a second read can sit beside the first: name it `demo/voice-<name>/`, so it stays out of git with the rest. A good build moves the last one to `demo-voice.prev.mp4`, and a failed one leaves it in place. `add` notes which take each part was recorded for, so after a new take the build refuses a part whose beat changed or moved more than half a second, and says which. Record that part again, or add the same file again to keep it.

**Who records.** The person speaking does. Recording under WSLg needs the Windows microphone, which a command sandbox can't reach, so they run this line themselves: at the Claude Code prompt with a leading `!`, or in their own terminal when it runs over 2 minutes, since a `!` line may be stopped there.

```
d=$(mktemp -d /tmp/voice.XXXXXX) && ffmpeg -nostdin -hide_banner -loglevel error -f pulse -i RDPSource -t SECONDS -ac 1 -c:a pcm_s16le "$d/PART.wav" && echo "$d/PART.wav"
```

It works only under WSLg; elsewhere, have them record with any app. Give it to them from here, never from `demo/` or the output of any script, since this session and the app can change those, and the user runs the line with no sandbox. Replace only `SECONDS`, with the whole number `cues` gives for that part, and `PART`, with `all` or the beat number. Check both before you hand the line over: `SECONDS` must match `^[0-9]{1,4}$` and `PART` `^(all|[0-9]{1,3})$`. If either doesn't, stop and tell the user, since `cues` comes from a file the app can change. It runs only ffmpeg, for that long, writes only into a folder it has just made under `/tmp`, which the sandbox can't write, and prints the file's path. When they give you the path, run `add` with it yourself, and tell them the recording also stays in that `/tmp` folder until they delete it. Nothing the user runs ever writes into `demo/`: a link planted there could turn that write onto any file they own. So never ask them to run `voice.mjs` or `captions.mjs`, which load the project's own `beats.mjs` or data, never run the line for them with the sandbox off, and never run `voice.mjs` with the sandbox off, or `captions.mjs` either. If they aren't at the machine with the microphone, any phone or laptop recorder works: they send the file, and `add` takes it. Under WSLg, the microphone must be the Windows default input.

A voice recording is personal data, so `demo/voice*/` stays out of git, whatever the event's rules say about `demo/`.

| Message | Meaning |
|---|---|
| `too quiet to be a voice` | The recording has no voice in it: the wrong input device, a muted one, or nobody spoke. A room with nobody talking measured -31 dB. |
| `clipped` | Not fatal, but listen to it. Turn the input down, or back off the microphone. |
| `ends while the voice is still going` | Not fatal: the recording may have stopped early, for example a `!` line stopped at 2 minutes. Listen to its end. |
| `runs ... s past the end of the take` | The read is longer than the take. Read faster, or add waits to the beats in `beats.mjs` and retake. |
| `only ... dB over the room's noise` | Not fatal, but the voice barely stands out, so its start and end are rough. Listen, and record somewhere quieter or closer to the microphone if it's off. |
| `runs ... s, and beat N has ...` | The clip is longer than the room it has. Shorten it, or add a wait to that beat in `beats.mjs` and retake. |
| `has no stretch of speech` | Only short sounds such as clicks, no voice. |
| `recorded for an earlier take` | A new take moved or changed those parts' beats. Record them again, or `add` the same file again to keep it. |
| `name it all.<ext>` or `this take has beats` | A file in `demo/voice/` has a name this can't place. |
| `the build came out silent` or `came out wrong` | ffmpeg made a bad file. The last good build is untouched. Report it, with `ffmpeg -version`. |

**Believe it only after listening.** The checks prove the file's shape, not that it sounds right. Have the user play `demo-voice.mp4` to the end, listening for crackle, a robotic tone, and the voice drifting off the captions.

## Captions

Judges often watch with the sound off, so captions are on by default: subtitles that repeat each spoken line, a label of 6 words or fewer for each beat, and note boxes for extra detail. `demo/captions.mjs` burns them into a copy of the finished video, so the take and the voice stay as they are. Skip it only if the user says so.

Add these to `demo/beats.mjs`:

| Field | Does |
|---|---|
| `say` on a beat | The line spoken over this beat, a string. It becomes the subtitle. |
| `note` on a beat | `{ text, at }`: a note box shown for this beat, with `at` one of `top-left`, `top`, `top-right`, `left`, `center`, `right`, `bottom-left`, `bottom`, `bottom-right`. |
| `export const labels = 'after'` | The take draws no caption box in the page, and `captions.mjs` draws each caption as a label at the top of the finished video. The default, `'page'`, draws the box in the page during the take, and no label is added afterwards, so a label is never drawn twice. |

Use `labels = 'after'` for new beats when captions are used, since the template already sets it. If the user skips captions, set `labels = 'page'` before the take, or the video has no labels at all. Each step still records its caption, so `captions.srt` and the voice checks work either way. With `'page'`, subtitles sit above the page's caption box, and a caption that wraps to two lines can meet them. A beat with a bad field fails loud, at the take and in `captions.mjs`.

**Read the lines first.** `node demo/captions.mjs lines` needs only a take. For each beat it prints the number, start, length, label, said line, word count and note. This is the sheet to read the voiceover from, and the speech check: it flags a line with more words than fit at 2.3 words a second of its beat, and says by how many. Cut those words, or give the beat more time in `beats.mjs` and retake. A clip made with `BEATS=3-4` lists beats 3 and 4 under their own numbers, and names the part number `voice.mjs add` takes for each, since that counts within the clip. It also flags a label over 6 words.

**Place notes after looking.** Put a note only where that beat's frame has room and the voice pauses. Look at the frames first, as "Believe it only after looking" says: a note covers whatever is behind it, and a viewer can't read a note and follow a sentence at once.

**Build.** `node demo/captions.mjs` writes `demo/out/subtitles.srt` (the said lines, a long line split into cues of at most two lines of about 42 characters, timed by each cue's share of the words) and `demo/out/demo-captioned.mp4`, made from `demo-voice.mp4` if it exists and otherwise from the silent `demo.mp4`. Subtitles sit bottom centre, labels top centre, each note at its anchor, all on a translucent dark box sized from the video's height. The sound is copied untouched, the picture is encoded with the take's settings, and the length is checked against the input to within one frame. For a clip, set `OUT` to its dir. A good build moves the last one to `demo-captioned.prev.mp4` and `subtitles.prev.srt`, and a failed one leaves them in place. A new take or a new voice build moves `demo-captioned.mp4` aside with a warning, since it was made from the old one: run `captions.mjs` again.

It needs ffmpeg built with libass and a font libass can find: the build checks the first and test-draws a line for the second, since with no font ffmpeg exits 0 and draws nothing. The build refuses when `beats.mjs` no longer matches the take (an action changed, beats were added or removed, or a caption changed on a take that drew it in the page), naming the beat where it can: retake, or put `beats.mjs` back. Editing `say` or `note` needs no retake, only a new build, and with `labels = 'after'` neither does fixing a caption. If the voice is already recorded, record that part again too: subtitles repeat `say`, and nothing checks them against what was spoken.

**Known limits.** Subtitles follow the beats' times, not the speech itself, so a line read early or late still shows on its beat: keep each line close to its beat when recording. Glyphs come from the machine's fonts through fontconfig, so CJK text needs a CJK font installed. Word counts split on spaces, so text with no spaces counts as one word. The beats check reads each action's source, so a change to what a helper that builds the action was given isn't caught.

**Believe it only after looking**, for the captioned file too: extract a frame from each beat of `demo-captioned.mp4`, as in "Believe it only after looking", and check that the subtitle is legible, the label is on the right beat, no note covers what the beat shows, and nothing runs off the frame.

## Edit in invideo

invideo is a web video editor whose timeline you edit through its connector while a person edits the same timeline in the browser. Use it after the take, the voice if there is one, and the captions are built, for titles, transitions, music and moving a clip. What was measured here was measured on its claude.ai connector, with one person in the same account; the rest is marked unmeasured or unproven.

**Setup, once per machine.** These are installs: do them before the event, and never inside an install freeze the user keeps.

1. The user connects invideo in claude.ai's connector settings and signs in. Its tools then appear here as `mcp__claude_ai_invideo_Editor__*`; `current_user` shows the account and its credits. invideo's own instructions tell Claude Code to use its full connector (`https://mcp.invideo.io/mcp`) instead. That one is unmeasured, and its tools have other names, so the rules below wouldn't match them: stay on the claude.ai one unless the user chooses to switch, before the event.
2. Auto mode can refuse any of invideo's calls until it is allowed. The user adds these to `permissions.allow` by hand, in their user-level Claude Code `settings.json`, and on a machine dotclaude installs, in its `settings.machine.json` too, so a rerun of its `setup.sh` keeps them. Each lets that one call run with no prompt, on invideo's servers, as the signed-in account; invideo writes that code, and only the user writes the rule. The AI-generation calls, which spend credits, stay off the list, but auto mode may let one through anyway, so ask the user before any of them. Some rules reach further than their name: `add_media` also places paid stock, so a credit charge goes through unprompted; `edit_timeline` can delete or overwrite a teammate's work; and `timeline_history` can restore an older checkpoint over the current timeline (it backs up what was there first). The edits measured here spent no credits. Asking before anything paid and reading the timeline before each edit (below) are yours to do; no setting enforces them. The rules stay after the event, and so do the uploads, a voice included. When the team stops using invideo, tell the user to remove the rules and any invideo hosts added below, and to delete the project in invideo's site if its files shouldn't stay there.

```json
"mcp__claude_ai_invideo_Editor__current_user",
"mcp__claude_ai_invideo_Editor__new_project",
"mcp__claude_ai_invideo_Editor__register",
"mcp__claude_ai_invideo_Editor__new_timeline",
"mcp__claude_ai_invideo_Editor__start_upload",
"mcp__claude_ai_invideo_Editor__add_media",
"mcp__claude_ai_invideo_Editor__timeline_history",
"mcp__claude_ai_invideo_Editor__edit_timeline",
"mcp__claude_ai_invideo_Editor__search_library",
"mcp__claude_ai_invideo_Editor__export",
"mcp__claude_ai_invideo_Editor__leave_timeline",
"mcp__claude_ai_invideo_Editor__get_timeline",
"mcp__claude_ai_invideo_Editor__timeline_catalog",
"mcp__claude_ai_invideo_Editor__read",
"mcp__claude_ai_invideo_Editor__status"
```

Give the user this block for the settings files, not for `/permissions`, which saves a pasted block as one rule that matches nothing. A file with no allow list yet takes it inside `"permissions": {"allow": [ ... ]}`. Pasted into an existing list, it needs a comma on each side that has an entry: after the entry before it, and after its own last line when entries follow. A settings file that doesn't parse breaks dotclaude's `setup.sh` merge.

3. Uploads go to `iv-prod-pro-uploads.s3.amazonaws.com` and exports come from `m.invideo.io`. In auto mode, pass the host in the Bash tool's `allowed_domains` on each `curl` call, which allows it for that call only. In any other mode, ask the user to add both to the project's allowed list in `.claude/settings.local.json`, as "Write the beats" says for any host, with a row in `ACCESS.md` if that file exists.

**Before uploading,** ask whether the demo shows anything that must stay private, and ask the speaker before their voice goes up: every file goes to invideo.

1. `new_project`, then `register` a name and pass it as `as` on every call, so your edits carry your own name. Give the user each URL you get back. When the user gives you a project or timeline URL instead, `register` there and work on it.
2. `new_timeline` at the take's size and frame rate, unless the team already has one.
3. For each file, `start_upload` returns a signed URL that carries a short-lived key. PUT the file with `curl -sS --fail -X PUT -H 'content-type: <type>' --data-binary @<file> '<url>'` (without `--fail`, an expired key's 403 still exits 0), with the file's own type (`video/mp4`, `audio/wav`). Then `add_media` with the `upload_id`. Read the media bin (`get_timeline`, `collection: asset`) before placing anything: uploads added in parallel are listed out of order. Export links are signed too and last a day. Keep both kinds of URL on the command line, never in a file.
4. Every change to the timeline, from placing a clip to a fade, is an op sent with `edit_timeline`. Edit the timeline the team works on, so everyone sees one cut: read it before each edit, look up an op's fields with `timeline_catalog` before its first use, and send `dry_run` first. "Someone's edit landed since your read" means someone else changed it: read it again and rebuild the edit on what is there now. For a change the team may throw away, `timeline_history` with `action: create_branch` makes a branch with its own URL and state token; nothing measured here merges a branch back, so export from the branch the team picks.
5. Place `demo/out/demo-captioned.mp4`, which carries the captions and any voice built before it. If it isn't there, run `node demo/captions.mjs` first, since a new take or voice build moves it aside and `labels = 'after'` leaves the other files with no text at all. Use `demo/out/demo-voice.mp4` instead only if the user skipped captions. Place it with `place_media` and `linked_audio` at frame 0: `voice.mjs` has already put the voice on its beats and checked it. A file with no voice, `demo/out/demo.mp4` or a `demo-captioned.mp4` built without one, has no audio, so `check` fails on it until music or a voice is added. The times below assume the take starts at frame 0; on a timeline with something before it, add the frame where the take starts. To move one beat's voice by hand, unlink the voice from the picture (`unlink_clips`), cut the voice in the silence just before and just after that beat's speech (`split_clip`, one cut per call, since the right half gets a new id), and move that piece (`move_clip`) no further than the silence beside it. `ffmpeg -i demo/out/demo-voice.mp4 -vn -af silencedetect=noise=-30dB:d=0.1 -f null -` lists those silences in the take's own time. Don't cut at the beat's edges: beats touch, and the next beat's words can start right after the boundary, so a piece moved later writes over them. Listen after the move. A beat starts at its `start` minus `trim` in `demo/out/steps.json`, in seconds; times the take's fps gives frames, and invideo keeps fractional frames. To check one change fast, export only that stretch, as in step 7, with `start` and `end` in seconds. Don't upload the files in `demo/voice/` to place them one by one: they keep the silence `voice.mjs` trims, so each would land late.
6. A title from `add_text` with `align: center` came out in the middle of the frame, over the app, and white text on a light page was hard to read. Move it off the controls with `set_position` and give it a `background_color` (both unmeasured), then look at a frame of it.
7. `export` with `format: video`, `quality` set to the take's height, `fps` to its frame rate, and `encode_quality: best`, the only setting measured. Poll it with `status` until it completes, then `read` the URL `export` returned: the file's signed link is under `export.files`. Download it to a file of its own, such as `demo/out/edit.mp4`, so it doesn't overwrite the take: `curl -sS --fail -o <export> '<link>'` (`--fail` again, since a day-old link's 403 would otherwise be saved as the video). Then run `node demo/voice.mjs check <export>`. Look at frames from it as you would a take. When your part is done, `leave_timeline` takes your cursor off.

**Measured.** Edits land to the frame: six clips placed at fractional frames came out within 3.5 ms of `voice.mjs`'s own build, and a beat's voice cut out of `demo-voice.mp4` and moved 12 frames came out 400 ms later, with its neighbours untouched. Exports show no watermark, cost no credits, come back with stereo audio and a BT.709 colour tag, and may lose the take's last frame (33 ms): a 508-frame take came back with 507, likely because invideo stored its length to the millisecond and rounded down, while a 180-frame one kept all. `check` still passes. A 3-minute export took between 34 and 126 s and downloaded in under 30 s, but one 17 s export took about 4 to 5 minutes (not timed closely), so leave time for a slow one. At `encode_quality: best`, busy footage came back at about 15 Mbit/s, so a 229 MB upload returned as 342 MB, while a 3-minute UI demo came back at 13 MB: under a file-size cap, re-encode with a higher `-crf`. **Unproven:** teammates editing from their own accounts, whether they see your cursor, the full connector, a lower `encode_quality`, and venue Wi-Fi speeds.

**Stock music and footage** come from `search_library`, which is free. `add_media` with `stock` charges credits: a track quoted at 0.05 credits took 0.5. Ask the user before each one, and compare `credits_remaining` from `current_user` before and after. invideo licenses its stock and gives no licence text, so check `EVENT.md`'s "Third-party material" field first. An event that allows only freely available or openly licensed material rules it out: upload a file under such a licence instead, and note its source.

## Hand edits

For anything `voice.mjs` and invideo don't do, use a drag-and-drop video editor: Clipchamp comes with Windows 11, and Canva takes uploaded video and audio in its own editor (its connector refuses them). Any editor that exports H.264 MP4 works. Don't build one.

1. Import `demo/out/demo-captioned.mp4`, running `node demo/captions.mjs` first if a new take or voice build moved it aside. Use `demo/out/demo-voice.mp4` or `demo/out/demo.mp4` only if the user skipped captions or a cut needs new ones. The first two have the voice on its beats already. A file from `demo/voice/` keeps the silence before its speech that `voice.mjs` trims, so line up where its speech starts, not where the file starts. For a Windows app, copy them to a Windows folder first. Captions in the picture stay there, so edit from a file without them if a cut needs new ones.
2. Edit, then export at the take's size and frame rate.
3. Run `node demo/voice.mjs check <export>`. It fails on the wrong size, frame rate or codec, and on missing or silent audio. It reports the length and doesn't judge it, since an edit may change it, so compare that with the limit in `EVENT.md`.

Three things to tell the user before they start:

- An online editor uploads the video to that company, so ask whether the demo shows anything that must stay private.
- Stock music, footage or effects from an editor are third-party material: note where each came from and its licence, and follow `EVENT.md`'s "Third-party material" field.
- Free plans change, and can limit upload size or add a watermark to paid stock. Check the export before relying on it.
