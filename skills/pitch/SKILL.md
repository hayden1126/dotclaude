---
name: pitch
description: "Prepare a hackathon pitch to fit the event's format and length: the live demo and the backup video kept apart, a live-capability check, a written switch rule, Q&A from the judging criteria, slides before their deadline, timed rehearsals and a checklist for the hour before."
argument-hint: "[format or slot length]"
disable-model-invocation: true
---

# Pitch

From the user: $ARGUMENTS

This covers an expo table as well as a stage: read "on stage" below as wherever judges see the demo. A video-only event needs only the Video only section.

Two things, kept apart:

- **The live demo:** the team runs the actual product in front of the judges.
- **The backup,** if `EVENT.md`'s Video section or the user wants one: the video made with `/demo-video`, which the user asks for. Without that skill, any clean screen recording of the product works. It's never passed off as live.

## Start

Read `EVENT.md`. If it's missing, ask for only what this needs: format (live, video, both, expo table), length, Q&A time, slides deadline and whether there is a backup video. Either way, ask about `What must run live` and `Venue screen size and network` when the field is missing or marked unknown, since the live demo rests on them. If the event hasn't published a field, say so and use a stated guess, marked as a guess in `PITCH.md`, with the date to re-check it. Replan when the real value appears. Read `DEMO.md` if it exists: its script, seeded parts and honesty decisions carry over.

Write the plan to `PITCH.md`. In a public repo, ask where it goes first, since Q&A prep may not be for the public.

## The plan follows the format

| Format | Plan |
|---|---|
| Live | Default: motivation, then mostly live demo, then technical challenges, with where the world is heading if it fits. |
| Video only | See below. |
| Expo table | A short walk-up loop that restarts cleanly, a longer cut for a judge who stays, and a reset between visitors. Sort out power, screen and network at the table. The sections below apply there too. |
| Both | A plan for each. |

Give each part a time. The parts fill the slot and don't overrun. If it runs long, cut content rather than talk faster. "Talk as long as you can" applies only where no limit exists.

## Video only

The video is the pitch, so effort goes there: ask the user to type `/demo-video`, and fit it to the length and format in `EVENT.md`. Skip the rest of this skill, keeping Q&A and slides only if the event has them.

## Q&A and slides

For each judging criterion, write the likely questions, a two-sentence answer and who answers. Always include "is that real?", answered from the seeded parts in `DEMO.md`. Also include what's hardest, what's next, and how AI was used if the rules ask. "I don't know, here's how we'd find out" is a fine answer. A bluff isn't.

Slides: find their deadline, which can fall well before the pitch, and finish before it. Keep a copy on the presenting machine. Slides carry the motivation and the challenges; the product carries the demo.

## The live demo

Nothing depends on this agent, its setup or the machine it runs on, since a teammate may present from their own laptop.

- Rehearse on the presenting machine, in the browser they'll use, at the size in `Venue screen size and network`.
- One person drives while another talks. Name them.
- A local offline copy on the presenting machine is one possible fallback, not a requirement. Some events require live capabilities on stage.

## Live-capability check, at rehearsal

List each thing that must really happen live, starting from `What must run live`: real backend, live AI call, real-time data, hardware.

| Live thing | Time it takes, measured | Depends on | Fallback on stage |
|---|---|---|---|
| ... | | network, an outside API and its rate limit, a cold start, a device | a cached answer, seeded data, a recording of that step, a second network |

Then settle how services stay warm, check the spend cap on each paid key has room, and run one rehearsal on the venue's network or a hotspot. Whether a slow step runs live or starts before the pitch is the team's call from that timing. If it starts earlier, say so on stage. A fallback showing cached or seeded output is disclosed as `DEMO.md` decided. If the event requires a capability live, a fallback keeps the talk going but doesn't meet the rule.

## The switch rule

Write it down before the first rehearsal. Nobody debates it on stage.

- **What failure:** for example an error page, a blank screen, or no response.
- **How long you wait:** a number of seconds, set from the measured times above, and whether one retry is allowed.
- **Who says it:** one named person says the switch line: "switching to the video", or the fallback from the check above when there's no video.

A video sits as a local file on the presenting machine, open and cued, not behind a link. Decide who narrates over it. With no video and no fallback, the rule is what the team says and shows instead: a slide, the last good state, or how it works at a whiteboard.

Put one line pointing at this rule in `DEMO.md`'s Backup.

## Rehearse

Twice at least, timed by someone with a clock. Log each time in `PITCH.md`. One run practises the switch rule for real. Over the slot? Cut, and run it again.

## The hour before

- Machine charged, charger and the adapter for the venue's screen in hand. Tested on the real screen if allowed.
- Notifications off. Other apps closed. No personal tabs, autofill or keys on screen. Zoom level set.
- Services warm, spend caps have room, the network and its backup both tried.
- Demo data reset to the first beat. Anything the team chose to start early is running or done, with its result ready.
- One last run of the demo path. After that, no code changes or rebuilds.
- The video, if there is one, and the slides open locally. Slides submitted, if they were due.
- Driver, talker, Q&A owners and timekeeper all know their part. The switch rule read aloud once. Room and running order confirmed.
