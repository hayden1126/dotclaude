---
name: verify
description: Launch and drive <fill: app name>, the <fill: surface, such as web app or API>, to prove a change works on the running app, with evidence and cleanup in one command. Use to run, start, launch, screenshot or verify the app, and before a commit, push or ready PR whose change can reach a user path. Not for unit tests alone.
---

# Verify <fill: app name>

`verify.py` starts the app, checks it, drives it like a user, saves evidence and tears it all down,
inside one command. The harness lives in `<fill: harness folder>/`, outside `.claude/` so sandboxed
Bash can write it; this file is the only part kept here. Edit `journeys.py` there and this file only.
`verify.py`, `browser.py`, `LICENSE-pstack-claude` and `CHECKSUMS` are copies:
`sha256sum -c CHECKSUMS` from the harness folder shows whether they still match.

## When to run

Choose the tier from the paths this commit will contain: `git diff --cached --name-only`, plus any
paths named on the commit. For `git commit -a`, which also takes every tracked change in the working
tree, use `git diff HEAD --name-only` instead. Otherwise not from `git diff` or `git status`, which
show the working tree, and not from the whole index.

| Tier | When | What runs |
|---|---|---|
| full | A change that can reach a user path, dependency and config changes included | launch, doctor, the journey that covers it |
| quick | A WIP commit on a branch, or the user says quick | launch and doctor |
| skip | Only paths listed below as unable to reach the app; a conflict-free merge; a pre-launch blocker (exit 2); or the user says skip | nothing |

Paths that cannot reach the app: <fill: paths or globs, such as docs/ and *.md, or "none">.

When no journey covers the change, say so in the reply, then do one of two things and report which:

- Extend a journey or add one. Plant a wrong expected value in its new `ctx.check` and see exit 1
  first, then revert the value. Keep the journey when the feature matters to users.
- Run a temporary check under the same rule (plant a wrong value, see exit 1, revert), then remove
  it, so the commit holds only the change.

A skip or a quick run is never silent: the reply says which tier ran and why. A boot crash is exit 1
and never a reason to skip. A full run comes before any push and before a PR goes ready, whatever the
commits did. To turn the commit-time prompt off for a stretch, add `disable-model-invocation: true` to
this file's frontmatter.

## Launch

```
python3 -B <fill: harness folder>/verify.py                 # full: every journey
python3 -B <fill: harness folder>/verify.py --journey NAME  # full: one journey
python3 -B <fill: harness folder>/verify.py --quick         # quick: launch and doctor, no browser
```

Run it as one Bash call, from any folder: the harness finds the repo root itself. **Why one
command:** each sandboxed Bash call gets its own network and pid namespace, so a server started in
one call is invisible to the next. Nothing checked from a later call proves anything: the port
always looks free and the process group always looks empty. The harness records those facts itself,
in the manifest. `-B` keeps bytecode out of the repo.

Measured `duration_seconds`, warm (the first run in parentheses): full not measured yet, quick not measured yet.

| Exit | Meaning |
|---|---|
| 0 | Proved |
| 1 | The app failed: boot crash, ready timeout, doctor failure, journey failure |
| 2 | Could not judge: no browser, port held, preflight refused, bad config or a missing recipe, a journey bug (its own error, a result the browser can't send back, or no check), the browser itself died or never opened a tab, or the run was interrupted. A boot crash is never exit 2 |
| 3 | Cleanup failed. Wins over 0, 1 and 2; the manifest keeps both results |

## Doctor

`DOCTOR` in `journeys.py`: GET rows of path, status and text, polled until all pass or
`ready_timeout` runs out. They are data so they can't do more than read. Ready means usable, not
just that a process answers.

## Drive

Journeys use the real user path: the clicks and fields a person uses, never a test-only endpoint or
an internal setter. A journey that runs no `ctx.check` is not judged (exit 2). `FORBIDDEN_REQUESTS`
names what a run must never send (a paid API, an email, a publish); a hit fails the journey.

Find a control by its id, ARIA label or a data attribute. One with none of those is clicked by its
visible text with `ctx.page.click_text`, which fails unless exactly one visible element matches. An
element matches when the text equals its rendered text (`innerText`, which applies CSS such as
`text-transform` and leaves out a hidden span), with every whitespace run collapsed to one space and
the ends trimmed, case-sensitive. Only when no element's rendered text matches does it fall back to
the source text (`textContent`, collapsed the same way). Never by position alone. Before the first
click, wait with `ctx.page.wait_for` for a sign the client is live (a request the client makes, or
a value only client code sets): `goto` waits for the load event, and on a server-rendered page a
click before hydration is lost without an error.

## Evidence

Each run writes `<evidence_dir>/<UTC stamp>-<tier>-<random>/`: `manifest.json`, `app.log`,
screenshots, `network.json` and `downloads/`. Read the manifest, not the console. Search `app.log`
and other evidence with `grep -a`, or read it in Python: a grep that takes the file for binary
(ugrep can) prints no matches and no error. Proof rules:

- Capture the action and its result, not just a final screen.
- Check side effects (a downloaded file, a written row) as well as what is visible.
- Open the screenshot and look at it before calling a run proved.
- A check that can't fail proves nothing. After changing a journey, plant one wrong expected value
  in a `ctx.check` (not in a `wait_for`, which only times out), see exit 1 with that check's
  message, then revert it.

## Cleanup

The harness ends the app's process group, then sweeps for any process carrying the run's token (a
`setsid` child leaves the group), and records `port_free_after` and `processes_left`. On exit 3,
tell the user each process in `processes_left`. Never signal one marked `outside_repo`: it may be a
shared daemon. Never kill by name. A manifest still saying `"running"` means the harness was killed:
outside a sandbox, end the group `app_pid` names, after checking that `/proc/<pid>/environ` holds the
manifest's `token`. Evidence is never deleted by cleanup.

## Features

| Feature | Journey | How a user reaches it | What proves it |
|---|---|---|---|
| <fill: feature> | <fill: JOURNEYS key> | <fill: route and clicks> | <fill: observable end state> |

## Not covered

User-facing surfaces no journey covers, each with the source path that shows it. Add a journey for
one only with the user's say.

- <fill: each surface no journey covers, with its source path, or "none">

## Known edges

- Linux only for the process sweep (`/proc`) and the browser lookup. macOS is untested.
- The commit-time trigger is a prompt, not a gate: it can be missed, so nothing should treat it as
  enforcement.
- The port check sees only this run's namespace. `preflight` covers what it can't see, such as
  another server's lock file.
- `FORBIDDEN_REQUESTS` detects a hit after the fact, from this tab's network log. It can't block it,
  and it doesn't see calls the server makes, popups or workers' own requests.
- A process that clears its environment escapes the token sweep once it leaves the process group.
- Needs Python 3.10 or later, git, and `chrome-headless-shell` for browser journeys (`VERIFY_CHROME`
  names one).
- The evidence dir must be outside the dev server's file watcher as well as git-ignored: evidence
  written where the watcher looks sets off reloads that slow the run and flood `app.log`. It must
  never be a test runner's output folder (Playwright's `test-results/` or `playwright-report/`,
  Cypress's `cypress/screenshots` or `cypress/videos`): the runner empties it at the start of each
  run, a spec a journey runs included. Under `node_modules/.cache/` it is lost on a fresh `npm ci`.
  A run folder deleted mid-run is made again, with its `downloads/`, at the next write, but what
  it held is gone, and so is the app's later output: it goes on into the deleted `app.log`.
- Reload or rebuild lines in `app.log` are a signal, not a diagnosis. Confirm the trigger before
  moving anything: for Vite, one run with `APP["env"]` set to `{"DEBUG": "vite:hmr"}` logs the file
  behind each update. Move the evidence dir only if the triggers are under it. A known source: in
  the Claude Code sandbox, sandboxed Bash mounts `/dev/null` over protected dotfiles at the repo
  root (`.bashrc`, `.gitconfig`, `.claude/settings.json` and others), which a watcher that scans
  the repo, such as Tailwind's source scan, sees from the first CSS compile on. That needs no change
  here: fixing it is app config (the watcher's ignore list) and the user's call.
- <fill: app-specific edges, such as a lock file left after a SIGKILL, or "none">

<!-- Adapted from pstack's create-verification-skill and maintain-verification-skill
(github.com/cursor/plugins, MIT, Copyright (c) 2026 Lauren Tan, via
github.com/michael-denyer/pstack-claude, MIT, Copyright (c) 2026 Michael Denyer), text in
LICENSE-pstack-claude in the harness folder. -->
