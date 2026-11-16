# WATCH: how the watch list is made

Baseline as of 2026-11-12; changes only via `12-retro`.

The watch list is a page of explainer videos per idea of the course, best first, with a notes row
where no video is good (FB-194): `practice/videos.html`, which `scripts/videos.py` builds from
`practice/videos.json`. These rules say which videos go on it, in what order, and what each row
says. The JSON's shape and its checks are `videos.py`'s docstring; the page's look is the notes
chassis's (`CHASSIS.md`); the run is `08-practice`'s "Watch list" step, and the agents' briefs are
in `agent-briefs.md`. A hub keeps a copy in `_build/WATCH.md`.

Ids are stable. A retired rule is struck through and keeps its number. A topic is one notes
section; an idea is one row group inside it, mapped to the notes subsections it teaches.

## Ranking

- **W1. Clarity first.** Rank the video a reader who skipped the lecture follows on one watch
  above a fuller one they can't follow.
- **W2. Visuals that build.** Rank drawn or animated visuals (a diagram built up step by step, a
  trace worked on screen) above word-heavy slides read aloud.
- **W3. Clean narration.** Rank down rambling talk (restarts, self-corrections, tangents) and
  frequent fillers.
- **W4. A voice.** Rank low an animation with captions only and no voice.
- **W5. Shorter wins a tie.** At equal coverage, the shorter video (or segment) wins.
- **W6. Volume never counts.** Never rank a video down for quiet audio: give it a `quiet audio`
  chip at most.

## Search

- **W7. Eight results.** Judge the top 8 results of each idea's search, not the top 4.
- **W8. Every subsection covered.** Run one gap search for each notes subsection of the topic that
  no candidate covers yet, and search again until each has a candidate or an explicit "none" (a
  notes row, W24).
- **W9. No coding tutorials.** Skip a video that teaches a language or a library in place of the
  idea.
- **W10. No length cap.** Never reject a video for its length: judge the stretch the row points
  at.
- **W11. A lecture by its chapters.** Judge a full lecture by its chapters, and point the row at a
  segment cut from it (its start and end), never the whole lecture.
- **W12. The student's links.** Rank the student's own links on these same rules; a kept one is
  shown as "your pick" (kind `yours`).
- **W13. Chase every gap.** Every gap an agent flags gets a gap search (W8) or an explicit
  "none".

## Folding

- **W14. One video per idea.** Keep the best one; the rest fold (W16) or are cut.
- **W15. One series.** Prefer one lecture series across ideas when it is as good as the
  alternative: its notation and its voice stay the same from row to row.
- **W16. Fold, don't add.** A second video's unique point becomes a `+ also` line under the first
  (its `also` field), never a row of its own.
- **W17. Merge neighbours.** Merge adjacent segments of one video into one row (`videos.py`
  refuses two stretches of one video in one idea that overlap or sit within 10 seconds).
- **W18. Overlap audit.** Before the list is shown, audit it for overlap across ideas and topics:
  no two rows teach the same point. Fold each overlap (W16) or cut it, and send every cut to the
  cut-loss review (W29).
- **W19. Never show a reject.** A rejected candidate stays in its ranker's output file, never on
  the page.

## Order and prerequisites

- **W20. Read back to the lecture's start.** For each segment, read its lecture from the start:
  every earlier chapter it names or relies on is covered by an earlier row, or the segment starts
  there.
- **W21. An intro box per topic.** Open each topic with its intro: what it is, how it differs from
  its neighbour topic, and how its rows build.
- **W22. Teaching order.** Run a topic's ideas, and so its rows, in teaching order: each after
  what it relies on.
- **W23. Two views.** Give each segment its lecture key and name the lectures, so the page shows a
  "by lecture" view beside "by idea".

## Rows

- **W24. A notes row where no video is good.** Put a notes row (kind `notes`) in its place, in
  reading order, linked to the live notes page. Give it a concise box (`explain`, STYLE S34's
  labels in S34's order) when its notes subsection has none.
- **W25. A thread line.** Give each row one line on what it picks up from the row before and what
  it sets up for the next.
- **W26. Differs from your notes.** Give each row its list of differences from the notes, notation
  and symbols first. A symbol that clashes with the course's (the same letter for another thing,
  another letter for the same thing) is the first line. An empty list means "matches your notes".
- **W27. How it's tested.** Give each row one line on the answer shape and what to write, taken
  from the notes' How it's tested lines (STYLE S9). Never a prediction (hard rule 8, FB-012).
- **W28. Gloss every symbol.** Gloss each symbol in plain words at its first use on the page
  (STYLE S15).

## Checks

- **W29. Cut-loss review.** After any cut or condensation, a fresh cut-loss reviewer per topic
  checks what was lost against the cut videos' points and the notes. Put each lost exam point in
  a `+ also` line.
- **W30. Validate the data.** `videos.py` exits 0 on `practice/videos.json` before the page is
  shown.
- **W31. Check the page.** `verify_page.mjs`, and `verify_videos.mjs` when the page has segments,
  pass on `practice/videos.html`; look at the shots.
- **W32. No key on the page.** While a mock is untaken, `mock_leak.py` prints LEAK OK on the page
  against the untaken mocks' keys: the student reads it before the attempt.

## Publishing

- **W33. Links only.** Link each video; never embed a player (the artifact host blocks embedded
  players).
- **W34. Private.** Publish the page private, like every artifact, and check its sharing setting
  (FB-118).
- **W35. No frames or transcripts in git.** Save no video frame or transcript in the hub's tracked
  files (course and video material is copyrighted, hard rule 5): kept at all, they go under
  `_build/videos/`, which is gitignored. Quote a transcript in an output file only a few words at a
  time.

## Tools

The main session does every fetch: the rankers search and judge, but a delegated agent can't run
`yt-dlp`, a Python program (L07), or reach a host the sandbox doesn't list (L02), so the main
session fetches each candidate's captions, chapters and storyboard frames into `_build/videos/`
between the rankers' two parts (`08-practice`, "Watch list", step 2). Each gotcha met in the first
run, with its fix, and the lesson that records it (`references/lessons.md`).

- **W36. A child eats the loop's input.** A shell loop that reads its list from stdin
  (`while read`) loses the rest of the list to a `yt-dlp` or `ffmpeg` it runs: give the child
  `< /dev/null` (L72).
- **W37. Caption languages and pace.** Auto-captions come as `en` or `en-GB`: ask for
  `--sub-langs "en.*,en"`. Caption fetches are rate-limited: pace them, one at a time with a pause
  (L73).
- **W38. Formats.** `yt-dlp` warns when no JavaScript runtime is installed, and some formats it
  offers are AV1, which a local `ffmpeg` may not decode: request H.264 (`-S vcodec:h264`) (L74).
- **W39. Storyboard frames, byte-exact.** Parse storyboard frames exactly: a parser that drops a
  byte per image corrupts every frame. Check that one frame opens before judging any (L75).
