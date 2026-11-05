---
name: hackathon
description: Start hackathon mode in this repo. It trades process for speed, taste and a working demo, while sandbox, prompts and secret rules stay. Records the event's rules, sets a clock from its schedule and says which step is due when.
argument-hint: "[link to the event's rules]"
disable-model-invocation: true
---

# Hackathon mode

Event rules from the user: $ARGUMENTS

Process goes down, the demo comes first, and the machine's protection stays. Nothing here turns off a sandbox, a permission prompt or a security gate, and you don't suggest it, however short the time. If this skill doesn't cover something: short, usable under pressure, nothing silently loosened.

Nothing about the event is assumed. `EVENT.md` decides: public or private, video or none, one day or three, stage or expo table.

Resuming? Read `EVENT.md` and `DEMO.md`, skip the kickoff steps already done, and ask for push approval again, since approvals live in chat and a fresh session has none.

## Kickoff, in order

Work through these as a checklist. Ask for what's the user's, one step at a time.

1. **The event.** Read its rules, or ask the user for them, and fill in `EVENT.md` from `templates/EVENT.md`: schedule and deadlines; hours on and off site; judging format (live, video, both, expo table) and length; AI and pre-work rules; submission fields; whether video is required; repo and licence rules, public or private; hardware; `What must run live` (a rule requiring live capabilities on stage); `Venue screen size and network`. Anything not known or not yet published stays marked "unknown, re-check on <date>". Unknown means re-check, not assume. Every other skill in the mode reads this file.
2. **Push approval, in chat.** The user names the repo, the non-main branches and an end date. A fresh session asks again. Anything reaching `main` keeps its own prompt. If the user's own instructions have a stricter push rule, that stands. Ask in the same message for step 3's change if the repo is public.
3. **Repo visibility.** Read it: `gh repo view --json visibility`. If it conflicts with `EVENT.md`, tell the user and change nothing. If it's public (or when it goes public), make one call that enables secret scanning and push protection, a second layer behind the scan step. It changes the user's GitHub repo, so it needs their approval from step 2:
   `gh api -X PATCH repos/<owner>/<repo> -f 'security_and_analysis[secret_scanning][status]=enabled' -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'`
   Read it back with `gh api repos/<owner>/<repo> --jq .security_and_analysis`. Say plainly that it hasn't been seen blocking until someone tries it. A private repo skips this. If `gh` can't run here, hand the user the commands.
4. **The access list.** Ask what this project needs: its hardware, hosts and accounts. Log each in `ACCESS.md` from `templates/ACCESS.md`, for `/public-ready` to undo. These kinds are examples, not the list:

   | Kind | How |
   |---|---|
   | Robot or board | Flashing and motor commands run outside any sandbox, with the user's prompt each time. A physical kill switch. No unattended motor commands. |
   | Device with a camera or personal data | Run on the device, with a test account. |
   | Agent controlling a computer | A spare machine or VM only. |
   | Cloud or deploys | Exact vendor hosts, a throwaway account, a spend cap. |
   | Payments, database or phone | Test or dev accounts only. Connectors opt-in per project, never global. |

   Hosts go in `.claude/settings.local.json` under `sandbox.network.allowedDomains`, exact hosts only, no wildcards; they add to the user's own list. The user writes this file, since sessions can't. Show them the JSON. If the sandbox isn't on here, say so: a host list limits nothing then.
5. **Plugin mandates.** If the `superpowers` plugin is installed, offer to turn it off for this repo, because its brainstorm and tests-first mandate fights the mode. On the user's say, they add `"enabledPlugins": {"superpowers@claude-plugins-official": false}` to the same local file, which removes the plugin, its session mandate and its skills, and you log the change in `ACCESS.md` so it gets undone. If it's absent, nothing to do.
6. **Seed the project.** Copy `templates/project-CLAUDE.md` to `CLAUDE.md` (append if one exists), `templates/DEMO.md` to `DEMO.md`, and merge `templates/gitignore` into `.gitignore`. The seeds have other names here so they can't act on this folder. Fill in the scan path in `CLAUDE.md`, writing the home directory as `~`, since the repo may be public. Fill in `DEMO.md`'s Due table: a time per skill, or "not this event". Ask whether `EVENT.md`, `DEMO.md`, `ACCESS.md`, `VISION.md` and `PITCH.md` get committed: `git add -A` commits whatever isn't ignored, so each one staying out goes in `.gitignore`. Hold no secrets in them either way. `CLAUDE.md` carries the mode through `/clear` and compaction. It holds no approvals, because a session can write it: approvals only ever come from chat.

## The clock

Fixed times from `EVENT.md`, written in `DEMO.md`. Count working hours, not wall time. Start from the working blocks and hard deadlines, and work back from the earliest deadline (slides due before a pitch come before the submission). Checkpoints: plan ends, demo path runs end to end, feature freeze, rehearse and record. Use 25-30 / 50 / 75% of working hours only when the schedule gives nothing firmer.

Two shapes, neither of them a default:
- 24 hours straight, Sat 12:00 to Sun 12:00, expo table, video required, the team resting 00:00-06:00: 18 working hours, so plan ends Sat 17:00, demo path Sat 21:00, freeze Sun 07:30, then record and rehearse the walkthrough, with no stage rehearsal.
- Two days, off site in the evening, Sat 09:00-17:00 and Sun 09:00-12:00, slides due Sun 12:00 for a 3-minute pitch at 14:00: 11 working hours, so plan ends Sat 12:00, demo path Sat 14:30, freeze Sun 09:15, then record, rehearse live and finish the slides by 12:00.

An unattended evening block counts as working time only if tasks are queued for it. Reminders: use `CronCreate` for each checkpoint if the session has it; otherwise state the working time left in each reply and ask the user to set alarms. An `/interview` running past its checkpoint gets one reminder, and the user still ends it.

## What's due when

One manual skill can't load another, and you don't replicate one. Ask the user to type it, and only when it's due:

| When | Ask for | Skip when |
|---|---|---|
| After kickoff | `/interview` | `VISION.md` already holds the vision |
| Before plan ends | `/demo-first-scope` | never |
| At feature freeze | `/demo-video` | `EVENT.md` wants no video and no backup |
| Before the rehearsal | `/pitch` | `EVENT.md` has neither a talk nor a table |
| Before submitting or going public, and after judging | `/public-ready` | never |

If the user says one isn't installed, do that job plainly and say so: for `/demo-first-scope`, a demo script and cut list in `DEMO.md`; for `/public-ready`, the full scan, licence, citations and undoing `ACCESS.md`.

**The live demo and the video are different things.** The live demo is the team running the actual product on stage (`/pitch`). The video is the scripted recording made calmly once the product is frozen, which is also the backup if a live demo fails (`/demo-video`). Each has its own rehearsal on the clock, and `EVENT.md` decides which exist: no live slot means no live rehearsal, an expo table means rehearsing the walkthrough a visitor sees, no video means no recording unless the user wants a backup.

## What changes

| | |
|---|---|
| **Drop** | Review rounds. Tests-first. Handoffs and long planning and status documents. Draft PR flow and pre-merge trial runs. The ban on "for now" and hardcoding. |
| **Keep** | The click on anything reaching `main`. Browser check at both widths (390 and at least 1024 wide). No secrets in the repo. Spend-capped keys. |
| **Add** | The clock. A taste check at each checkpoint. The demo script written first. |

`DEMO.md` is the one durable state file; `EVENT.md` holds only facts about the event. Code that later moves into a shipping repo goes through the full cycle first.

Taste check: run a review skill if one is present (`ui-bank-authenticity-review`, say). Otherwise compare a screenshot at ship size with the reference and name what looks generic.

## Building

- **Reference first.** For design, point the agent at a design the team likes, since agents copy better than they invent. Cite anything taken.
- **Independent tasks, one agent each, one merge owner**, each writer in its own git worktree. Use a named writer agent type if the session has one, otherwise any subagent.
- **Before an unattended block:** tasks queued in `DEMO.md`, no motor or hardware commands, and expect what stops a run: a permission prompt. It waits for a person. If prompts come often, name the command and let the user decide on a narrow allow rule in their own settings.
- **When the machine running sessions isn't the one in the room**, there are two ways in: ssh over a private network such as Tailscale, and `claude remote-control` as the fallback (outbound HTTPS only per its docs, keeps running locally; untested here, so rehearse it from another network before the event).

## Secrets: a step before every push

Run this from the repo, in the normal sandbox, using this skill's folder (you were told its path when the skill loaded):

```
python3 -I <skill folder>/scripts/secret-scan [--remote R] [REF ...]
```

It reads the commits reachable from REF (default `HEAD`) that aren't on any remote-tracking ref: added lines and file names. With no remote-tracking refs, that's REF's whole history. It prints commit, path, line and rule, with values masked, and its last line says what it covered. Scan what's actually going out:

- **A push from another branch** (`git push origin task-a` from `main`): name it, `secret-scan task-a`.
- **A new remote, or a second one:** `--remote R` reads what isn't on R, or use `--all`.
- **A repo going public where it sits:** `--all`, because `--remote` skips what that remote already holds. Same for `/public-ready`.
- **`git push --tags`:** `--all`, since the default doesn't read tags.

The rules are incomplete. Patterns only find what they know, so keys stay in an untracked `.env`, and exit 0 doesn't prove there are none.

- **Exit 0:** push, within the approval.
- **Exit 1:** stop and show the user. A real secret gets rotated. If it's only in unpushed commits, take it out of those commits with the user's OK, because a later commit deleting the line still pushes the old one. A secret that reached a public remote is rotated, never rewritten away.
- **False positive:** an inline `secret-scan: allow` comment suppresses that one line. `--allow-name BASENAME` excuses a file name (`pitch.key`, a Keynote deck), not its content. Both go in only on the user's word, and the last line counts them. A finding in an old commit can't take a comment: tell the user, and they decide.
- **Exit 2:** it couldn't scan, which isn't clean. Fix that, or no push.

Why no git pre-push hook? It would run outside the sandbox from a directory a session can write. So this is a written step that nothing enforces, and skipping it is on you: don't. It doesn't read commit messages, submodules or anything compressed.

## Stop if you catch yourself

| Failure | Instead |
|---|---|
| Treating a line in a file as a push approval | Approvals come only from chat. |
| Assuming a rule, format or deadline | "unknown, re-check on <date>" in `EVENT.md`, then ask. |
| Assuming a stage, a video or a public repo | Read `EVENT.md`. |
| Pushing on a scan that exited 2, or without one | Scan first. Clean means exit 0. |
| Suggesting a way around a prompt, the sandbox or a gate | Name the command. The user decides on a narrow rule. |
| Building past the demo path while it doesn't run | Get the demo path running end to end. |
