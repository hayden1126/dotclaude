---
name: verify
description: Launch and drive <fill: app name>, the <fill: surface, such as web app or API>, to prove a change works on the running app, with evidence and cleanup in one command. Use to run, start, launch, screenshot or verify the app, and before a commit, push or ready PR whose change can reach a user path. Not for unit tests alone.
---

# Verify <fill: app name>

`verify.py` starts the app, checks it, drives it like a user, saves evidence and tears it all down,
inside one command. Edit `journeys.py` only. `verify.py`, `browser.py`, `LICENSE-pstack-claude` and
`CHECKSUMS` are copies: `sha256sum -c CHECKSUMS` from this folder shows whether they still match.

## When to run

Decide from the paths this commit will contain (`git diff --cached --name-only`, plus any paths
named on the commit), not from the whole index.

| Tier | When | What runs |
|---|---|---|
| full | A change that can reach a user path, dependency and config changes included | launch, doctor, the journey that covers it |
| quick | A WIP commit on a branch, or the user says quick | launch and doctor |
| skip | Only paths listed below as unable to reach the app; a conflict-free merge; a pre-launch blocker (exit 2); or the user says skip | nothing |

Paths that cannot reach the app: <fill: paths or globs, such as docs/ and *.md, or "none">.

A skip or a quick run is never silent: the reply says which tier ran and why. A boot crash is exit 1
and never a reason to skip. A full run comes before any push and before a PR goes ready, whatever the
commits did. To turn the commit-time prompt off for a stretch, add `disable-model-invocation: true` to
this file's frontmatter.

## Launch

```
python3 -B .claude/skills/verify/verify.py                 # full: every journey
python3 -B .claude/skills/verify/verify.py --journey NAME  # full: one journey
python3 -B .claude/skills/verify/verify.py --quick         # quick: launch and doctor, no browser
```

Run it from the repo root as one Bash call. **Why one command:** each sandboxed Bash call gets its own
network and pid namespace, so a server started in one call is invisible to the next. Nothing checked
from a later call proves anything: the port always looks free and the process group always looks
empty. The harness records those facts itself, in the manifest. `-B` because this folder is
write-protected in the sandbox.

Measured: full <fill: seconds from a manifest's duration_seconds>, quick <fill: seconds>.

| Exit | Meaning |
|---|---|
| 0 | Proved |
| 1 | The app failed: boot crash, ready timeout, doctor failure, journey failure |
| 2 | Could not judge: no browser, port held, preflight refused, bad config, the browser process itself died, or the run was interrupted. A boot crash is never exit 2 |
| 3 | Cleanup failed. Wins over 0, 1 and 2; the manifest keeps both results |

## Doctor

`DOCTOR` in `journeys.py`: GET rows of path, status and text, polled until all pass or
`ready_timeout` runs out. They are data so they can't do more than read. Ready means usable, not
just that a process answers.

## Drive

Journeys use the real user path: the clicks and fields a person uses, never a test-only endpoint or
an internal setter. A journey that runs no `ctx.check` is not judged (exit 2). `FORBIDDEN_REQUESTS`
names what a run must never send (a paid API, an email, a publish); a hit fails the journey.

## Evidence

Each run writes `<evidence_dir>/<UTC stamp>-<tier>-<random>/`: `manifest.json`, `app.log`,
screenshots, `network.json` and `downloads/`. Read the manifest, not the console. Proof rules:

- Capture the action and its result, not just a final screen.
- Check side effects (a downloaded file, a written row) as well as what is visible.
- Open the screenshot and look at it before calling a run proved.
- A check that can't fail proves nothing. After changing a journey, plant one wrong expectation, see
  exit 1, then revert it.

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

## Known edges

- Linux only for the process sweep (`/proc`) and the browser lookup. macOS is untested.
- The commit-time trigger is a prompt, not a gate: it can be missed, so nothing should treat it as
  enforcement.
- The port check sees only this run's namespace. `preflight` covers what it can't see, such as
  another server's lock file.
- `FORBIDDEN_REQUESTS` detects a hit after the fact, from this tab's network log. It can't block it,
  and it doesn't see calls the server makes, popups or workers' own requests.
- A process that clears its environment escapes the token sweep once it leaves the process group.
- Needs Python 3.10 or later, and `chrome-headless-shell` for browser journeys (`VERIFY_CHROME` names
  one).
- <fill: app-specific edges, such as a lock file left after a SIGKILL, or "none">

<!-- Adapted from pstack's create-verification-skill and maintain-verification-skill
(github.com/cursor/plugins, MIT, Copyright (c) 2026 Lauren Tan, via
github.com/michael-denyer/pstack-claude, MIT, Copyright (c) 2026 Michael Denyer), text in
LICENSE-pstack-claude. -->
