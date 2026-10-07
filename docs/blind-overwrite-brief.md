# Brief: guard against blind overwrites and inferred job state

> Pre-design brief, not a spec. Written 2026-10-06 by a karaoke session (`~/code/karaoke`) right after
> the incidents below, at Hayden's request ("do a detailed report to dotclaude so another agent can
> work on it there"). The job: run the experiments in "Settle first", then `superpowers:brainstorming`
> with Hayden on the design space, then `writing-plans`, then implement on a branch. Push and PR only
> with his approval (CLAUDE.md).

## The problem

Two mistakes in one session, both on rules that already exist as prose:
1. The model overwrote a file it had never read, and nothing stopped it or kept a copy.
2. The model reported a job as finished from a timestamp and a resemblance to an earlier run, when
   the job's own finish marker said otherwise.

Prose did not bind in either case: Claude Code's own "Read before you overwrite" rule, and CLAUDE.md's
"Show evidence, not assertions". `docs/prose-is-not-a-permission.md` makes the same argument for
delegation. A guard that matters has to be a hook.

## Incident 1: the blind overwrite

**Timeline** (2026-10-06, EDT; Claude Code 2.1.289 (corrected from 2.1.292, see Results); karaoke session
`4c9dfc5e-45ab-47c6-8a18-8c674f3ff52b`, started by a `/clear` at about 19:13):
- **19:29.** Right after plan approval, the model called `Write` on
  `~/.claude/projects/-home-hayden-code-karaoke/memory/karaoke-personal-product.md` with the content
  `PLACEHOLDER`. It meant to read the file and fill it in afterwards. The call went in a parallel batch
  beside an unrelated Bash command, as a stub.
- **The damage.** The file held Hayden's product vision, setup, wants and dated decisions (6284 bytes,
  74 lines). It became 11 bytes. The tool answered "updated successfully".
- **The built-in guard did not fire.** The Write tool's contract says overwriting a file not read in
  the session fails. This session had never read that file. (Results: the Write tool's check stopped firing after 2.1.285.)
- **No backstop** (wrong: see Results, E2; file-history held the original). Memory directories are not under git, not snapshotted, and outside every repo.
  `~/.claude/backups` holds only `.claude.json` copies.

**Recovery**, 10 to 30 minutes later:
- **The first attempt was blocked.** A `grep -l` over the project's transcripts
  (`~/.claude/projects/<project>/*.jsonl`) was denied by the auto-mode classifier as "Irreversible
  Local Destruction". It went through only after Hayden explicitly said to recover from transcripts.
- **The source.** The last full `Read` of the file was in session `36959b35`, at
  2026-10-06T16:39:47Z. Its tool result carries the whole file with line-number prefixes.
- **Why it is the latest version.** The extracted frontmatter's `modified: 2026-10-06T07:45:45.520Z`
  matches the last `Edit` (session `86de571c`, 07:45:45Z), and no later tool call in any transcript
  names the file.
- **The restore.** Writing back needed `dangerouslyDisableSandbox`, because `~/.claude/projects` is
  write-denied inside the sandbox.
- **No second copy existed** (wrong: see Results, E2). Terrarium's memory has a file with the same name, but it is a different
  memory (the class-project boundary), not a backup.
- **Luck, not design** (for Bash edits only: see Results, E2). Recovery worked only because some session had once read the whole file
  through the Read tool. Earlier karaoke sessions edited memory files with Python heredocs in Bash, so
  a file touched only that way would have been unrecoverable.

## Incident 2: job state inferred, not read

**What happened** (same session, about 19:15). The karaoke round 28 run trains five jobs one after
another on EC2. `ec2_train.sh` copies each job's log and json back every 2 minutes. A job is finished
when its json has a `stopped` key (`finished()` in `spikes/s10-align/ec2_train.sh`). The model told
Hayden "A1 is done" because:
- the json's mtime had just changed;
- the log's last line was step 4500 at 45 minutes, which is exactly where the pilot's job had stopped
  on patience.

**What was true.** The json had no `stopped` key. The job ran to the 8000-step cap, about 80 minutes.

**The cost.** The run's timing was planned at 45 minutes a job instead of 80, and that was caught
only by chance. With the real duration, the last job ends about 10 minutes before the instance's
self-halt at 01:24. If the halt wins, the run exits before its evaluation.

## Settle first (cheap experiments, before any design)

- **E1: why did the built-in guard pass?** In a fresh session:
  1. Write over an existing file never read: does it refuse?
  2. Read a file, `/clear`, then Write over it without reading again: does it refuse?

  If (1) refuses and (2) does not, the read state survives `/clear`. The karaoke process may have read
  that memory file before an earlier `/clear` (session `36959b35` read it at 12:39 EDT, but whether it
  was the same process is unverified). Then the bug goes to Anthropic, and a feedback draft is already
  queued in that session. Either way, the hook below is still needed.
- **E2: does `/rewind` cover this case?** Claude Code checkpoints edits made by its file tools. Does
  "restore code" bring back a file outside the working directory (here, `~/.claude/projects/...`), and
  across a `/clear`? If yes, the README should name it as the first recovery path. It does not prevent
  anything.
- **E3: do hooks run inside the Bash sandbox?** Design B commits under `~/.claude/projects`, which is
  write-denied there. Check that a hook can write there.

## Design space (discuss with Hayden; the recommendation is the author's view)

### A. Overwrite guard (PreToolUse on Write, Edit, MultiEdit, NotebookEdit)

- **Snapshot before every write to a file git cannot restore**: untracked, ignored, outside any work
  tree, or tracked with uncommitted changes (`git ls-files --error-unmatch` plus
  `git diff --quiet HEAD --`).
  - Store: `${XDG_STATE_HOME:-~/.local/state}/dotclaude/overwrites/<date>/<session_id>/<abs path>`,
    mode 600.
  - Skip a snapshot whose hash matches the last one for that path, so a burst of Edits keeps one copy.
  - Prune after 14 days at SessionStart. Skip files over about 20 MB, with a log line.
- **Deny a Write that shrinks such a file drastically**, e.g. new content under 20% of an old file of
  at least 1 KB. Incident 1 went from 6284 bytes to 11. The deny message names the snapshot path and
  says: use Edit, or Read the file and Write it in full.
- **Fail open.** Any hook error allows the tool and logs the error. This is the opposite of the
  subagent policy hook, which fails closed. Only the explicit shrink rule denies.
- **Limits:**
  - Bash writes (`sed -i`, redirects, `cp`, `mv`, Python `write_text`) are invisible to it.
  - `rm` followed by a Write gets past the shrink rule. The guard targets accidents, not an adversary.
- **To decide:** the threshold; whether Edit gets snapshots only (yes, in the author's view); whether
  a placeholder-content rule (`PLACEHOLDER`, `TODO`, a lone ellipsis) adds anything beyond the shrink
  rule.

### B. Memory under git

- **A local-only repo over every project's memory directory.** Put its git dir outside Claude Code's
  tree: `--git-dir=$XDG_STATE_HOME/dotclaude/memory.git --work-tree=$HOME/.claude/projects`. That
  way, no `.git` appears among the project directories.
  - Track only `*/memory/**`. Transcripts are large and must never be tracked.
  - No remote: memory is private.
- **Triggers:**
  - PostToolUse on Write and Edit whose path is under `*/memory/`;
  - SessionStart (all matchers) and Stop, which catch Bash-made edits that A cannot see.
- **Concurrency.** Several sessions run at once. On index-lock contention, skip quietly; the next
  trigger commits. Never block a tool.
- **Why both A and B:** A covers every file but only tool writes; B covers memory against every kind
  of write.

### C. One clause in global CLAUDE.md

Under "Show evidence, not assertions": *a job's state comes from its own finish marker (the field or
log line its script checks), never from timestamps or its likeness to an earlier run.* It is prose,
so it is weak, but no hook can check a claim made in chat. It is the only measure aimed at incident 2.

### D. Recovery helper (optional)

A script that lists every tool event naming a path across `~/.claude/projects/*/*.jsonl` (Read
results, Write content, Edit pairs, Bash commands). It rebuilds the last known content from the latest
full Read or Write plus later Edits: what was done by hand above. The classifier gates transcript
reads, so it runs on Hayden's request. It is worth building only if A and B leave gaps.

**Author's recommendation:** A, B and C. A is the core: it both prevents the incident and makes any
other blind overwrite recoverable. B costs little, and it is the only backstop for Bash-made edits to
memory. Settle D after E2.

## Constraints from this repo

- `setup.sh` links hooks into `~/.claude/hooks/`. `settings.json` is the baseline that
  `merge-settings.py` merges (personal rules go in `settings.machine.json`). Hayden installs with
  `./setup.sh` outside the sandbox, since `~/.claude/settings.json` is write-denied inside it.
- An existing PreToolUse `*` hook routes subagent calls to `subagent-policy.sh`. The new hook must
  coexist with it and with `tmux-state.sh` (ordering and latency). Every Write and Edit pays its cost,
  so keep it to one or two git calls.
- README's hook table lists every hook and its install. Add rows. `tests/` holds the existing suites;
  add one in their style.
- Hooks receive `session_id` and `tool_input.file_path` in the payload (see the payload sweep, PR
  #63, and memory `cc-stop-hook-facts` for Stop's fields).

## Acceptance tests (proposed)

1. Replay incident 1. A Write of `PLACEHOLDER` over a 6 KB untracked file is denied. A snapshot exists,
   and the message names it.
2. A Write that creates a new file is allowed, with no snapshot.
3. An Edit of a tracked, clean file is allowed, with no snapshot. An Edit of an untracked file is
   allowed, with a snapshot. A second identical-content Edit adds no snapshot.
4. A broken state dir (unwritable) allows the tool and logs the error.
5. A memory file edited through Bash appears in `git --git-dir=... log` after the next SessionStart or
   Stop. Two sessions editing memory at once block no tool, and both changes end up committed.
6. E1 to E3's results are recorded in the PR or README.

## Out of scope

Recovering past overwrites beyond this incident; syncing memory across machines; any change to the
karaoke repo.

## Results (2026-10-06, branch `feat/overwrite-guard`)

Two claims above were wrong. The incident ran on Claude Code **2.1.289**, not 2.1.292: the
transcript line of the Write carries `"version":"2.1.289"`. And a backstop **did** exist.

**E1: the Write tool's check is gone; Edit's is not.** Across every transcript on this machine,
"File has not been read yet" fired on Write through 2.1.285 (last on 2026-09-30) and never after.
On Edit, it still fires through 2.1.289. A fresh `claude -p` on 2.1.292 overwrote an unread
2250-byte file and answered "updated successfully". Memory paths are not exempt: the check refused
an Edit of this same memory file on 2026-09-28. The karaoke session queued a feedback draft.

**E2: file-history had the file.** Claude Code backed up the full original (6283 bytes) to
`~/.claude/file-history/4c9dfc5e…/7d1be6026214695c@v1` at 23:29:41.324Z, milliseconds before the
Write, and logged it in the transcript as a `file-history-delta` with its `trackingPath`. The
Write's own result also carries the old content as `toolUseResult.originalFile`. So the restore
was one `cp` away, and the paths outside the working directory are covered too. What it misses:
Bash writes, and anything older than the transcript's retention (about 30 days). Whether
`/rewind` restores such a file is unchecked; nothing depends on it now.

**E3: hooks run outside the Bash sandbox.** A Stop hook writes `~/.local/state/dotclaude/ring.log`,
which the sandbox's write list lacks.

**What was built** (Hayden's calls):
- **A, cut down.** `hooks/overwrite-guard.sh` denies a Write over an unread file (read-proof, from
  the session's transcript) or a drastic shrink. There is no snapshot store, since file-history
  already is one.
  - A successful Bash command naming the file's path counts as proof: absolute, `~/`, or relative
    to the cwd it ran in, as a whole shell token. A bare basename matched too much: one session's
    `grep … README.md` in another repo proved `~/dotclaude/README.md`. Replayed over the 292 real
    Write-over-existing-file calls in the transcripts, read-proof would have denied 16 (34 without
    the Bash rule). The incident is denied either way.
  - Shrink would also have denied one deliberate rewrite after a Read (8.6 KB to 1.3 KB).
- **B, on SessionStart and Stop only.** `hooks/memory-git.sh`. No PostToolUse trigger, since
  file-history covers tool writes in between.
- **C**, as worded above, in global `CLAUDE.md`.
- **D, made cheap by E2.** `bin/claude-file-history <path>` lists and restores the backups. On the
  incident's file it lists 18 versions across 4 sessions in about 5 seconds.
