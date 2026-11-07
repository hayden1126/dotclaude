# The dependency lifecycle in a production repo

Four recipes for a repo that deploys. Each stands alone, and each stays out of the way until a dependency changes. Adopt them when the user asks, not by default.

## A per-dependency list

Keep one file in the repo with an entry per direct dependency:

| field | example |
|---|---|
| package | the exact name in the manifest |
| list | runtime, build or dev |
| why | the one job it does here |
| runs where | server, browser, build step, CI |
| licence | the SPDX id |
| alternatives | what was considered, including writing it |

A test keeps the file and the manifest in step: it reads both and fails on a package in one and not the other, and on an entry with an empty field. The test is the reason the list stays true, since nobody rereads a file like this. Read the manifest with a parser, never a regex, and cover each list the manifest has (dependencies, dev dependencies, optional dependencies).

## Admission questions

Answer these in the PR that adds a package:

- **Is it maintained?** The last release, the open security issues, more than one maintainer.
- **What licence?** Is it compatible with how this code ships?
- **How big?** For browser code, the bytes it adds to the bundle after compression.
- **Does it run code at install?** Its lifecycle scripts or build step, and what they do.
- **How many transitive packages?** Each one is another maintainer who can publish into your build.
- **Could we write it?** A few lines of code you own beat a package you have to watch.
- **Which list?** A dev tool in the runtime list ships to production.

## A production audit in PR checks

Run the ecosystem's audit in PR checks, limited to what ships (`npm audit --omit=dev`, for example), and fail the check at the severity the repo picks. High and critical is a common start.

Keep an exceptions file beside it, one entry per advisory:

- the advisory id and the package;
- a reason that says why it can't reach production here, not "no fix yet";
- an expiry date at most 90 days out.

The check fails when an entry has expired, when an entry has no reason, and when an entry's expiry is more than 90 days away. An expired exception is a prompt to look again, so it fails like a new finding. An audit run that can't reach the registry reports "no finding, registry unreachable" and passes: an outage upstream shouldn't stop every PR. Make that outcome visible in the check's output, and don't let it read as a clean result.

## An update bot

Point an update bot at the manifest and lockfile with these settings:

- **A cooldown for routine updates.** Wait some days after a release before proposing it (7 is a common choice). Most malicious releases are found and pulled within that window.
- **Security updates at once.** The cooldown doesn't apply to a fix for a known advisory.
- **Group the small ones.** Patch and minor bumps of dev tools in one PR, so review stays cheap.
- **No auto-merge where a merge deploys.** A merge that ships to production gets a person. Auto-merge is fine only where a merge is followed by another gate before production.

The bot's PRs go through the same checks as any other, including the audit and the list test above.
