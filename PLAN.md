# PLAN: re-arm long background waits (the watch guard)

> Written 2026-10-02 and revised the same day after the T0 probes. It's built in the session that
> planned it, so the planner isn't the implementer: a `writer` builds each task in a worktree, a
> fresh `reviewer` checks each diff, and the lead runs the suites and merges.

## Approach

**The gap.**
- A Bash command run with `run_in_background` is stopped at its timeout (30 minutes by default,
  2 hours at most), and Claude Code then wakes the agent once. A `Monitor` watch stops at 30
  minutes. Both specs come from the tool descriptions.
- On 2026-10-02 a main-thread agent watching a long detached job hit the 2-hour cap and ended its
  turn. Nothing woke it when the job finished.
- **It was told to stop** (probe P-b). The wake-up notification says: "If the work in progress
  still needs it, start it again with `run_in_background` and a longer `timeout`. If it already
  had the longest `timeout` allowed, do not restart it." At the 2-hour cap, the agent followed
  that note.

**The same gap in dotclaude's own Codex flow.**
- SKILL §5 says to launch `codex-delegate run` with `run_in_background`, and that "the exit
  notification wakes you".
- The wrapper's own `--timeout` defaults to 3h, and §5 never says to pass the Bash `timeout`. So
  the wrapper is stopped at 30 minutes, or at 2 hours with the timeout set. Codex keeps running,
  and nothing wakes the lead when it ends.

**The fix is enforcement, not prose.** Waiting is liveness, which the delegation design's rule
puts on the machine. The pieces:
1. **A waiter, `delegation-ledger wait`:**
   - it records a *watch*;
   - it exits before the cap with the exact re-arm command, so it never gets the "do not
     restart" note;
   - it runs outside the sandbox (the ledger is already in `excludedCommands`), because every
     sandboxed command gets its own PID namespace and can't see processes started elsewhere.
2. **A main-thread Stop hook, the *watch guard*.** It blocks a turn from ending in two cases:
   - one of the session's watches has lapsed (its condition is unmet and no waiter is alive);
   - a background command was killed at its time limit, even with no watch recorded (the *kill
     catch*). This covers the original failure, where no waiter was used.
3. **`codex-delegate` records its own watch**, and it stops waiting before the cap.
4. **An allow rule**, so a re-arm never stops at a permission prompt.

**Why C over the alternatives** (evaluated 2026-10-02 against every situation found):
- **Prose alone (A)** relies on the judgment that already failed, and the notification's own
  prose points the other way.
- **A waiter with no hook (B)** improves the odds, but it still asks.
- **A `CronCreate` heartbeat (D)** is rejected:
  - its jobs live only in the session, so a restart loses them;
  - each poll costs a turn;
  - the agent has to create it, which is prose again;
  - a forgotten job fires for 7 days.
- **D adds nothing C lacks.** Every way a waiter can end wakes the agent: done, failed, at the cap,
  or killed. The stop that follows runs the guard.
- **Unexplored:** a command hook with `async: true` and `asyncRewake` "runs in the background and
  wakes Claude on exit code 2" (the hooks reference). Its time limit and restart behavior are
  unknown. It is noted here, not pursued.

**Decisions taken:**
- **Option C:** Hayden chose it.
- **The kill catch:** Hayden chose it over watches only and over a launch-time warning.
- **How hard the guard pushes: block once per lapse, and once per killed task.**
  - It blocks the first stop with the re-arm command.
  - The next stop goes through, with a `systemMessage` warning, and the lapse is recorded as
    acknowledged.
  - The guard decides by its own record (`blocked_at`, under a lock), not by `stop_hook_active`.
    So a hook registered twice can't loop, and a block from another hook can't swallow this one.
  - Blocking until a drop would wedge the session on a broken waiter, or on a re-arm stuck at a
    permission prompt.

**Out of scope:**
- Subagents. BRIEF forbids ending a turn while a background command runs, and the deadlines
  (`policy.toml` `[deadline]`, 60-minute stop at most) cap them well under 2 hours.
- Teammates.

**Reuse:**
- `skills/delegation/scripts/delegation_common.py`:
  - `state_dir`, `pid_alive`, `proc_start`, `pids_visible`, `fold`, `read_rows`, `codex_state`;
  - `update_agent_state`'s mkstemp plus `os.replace` pattern, for a new `write_json`;
  - `_agent_path`'s basename guard.
- `delegation-ledger`:
  - its argparse layout (`sub.add_parser`, `set_defaults(fn=cmd_x)`, the docstring usage block);
  - `live_sessions()`, for the sessions-file fields.
- `delegation_checks.log_error`, which appends to `delegation-ledger.err`.
- `report-check`, as the template for a Stop script (`decide` plus a fail-open `main`).
- `delegation_checks.evaluate` and `render`, for the session-start line.
- The live harness, `tests/delegation/run.py`.

## Tasks (bite-sized, ordered, independently verifiable)

### T0: Probe the assumptions C rests on (done 2026-10-02, Claude Code 2.1.286)
The probing session ran 2.1.286 (`CLAUDE_CODE_EXECPATH`). `claude --version` printed 2.1.287
because it reports the newest installed version, not the running one, so record the version
from the session's own executable.

A kill notice that arrives mid-turn is stored differently from one that starts a turn: as
`{"type": "attachment", "attachment": {"type": "queued_command", "prompt": "<task-notification>...",
"origin": {"kind": "task-notification", ...}}}`. The kill catch matches both shapes.
All of these ran in an interactive session with a temporary Stop hook in the project's
`.claude/settings.local.json`, which was removed afterward. Hook edits load live, as the
settings docs say.
- **P-a, passed.** The Stop hook fires on a turn that a background notification started.
  `{"decision": "block", "reason": ...}` keeps that turn going, and the reason arrives as a
  system reminder. The stop after the block carries `stop_hook_active: true`.
- **The Stop payload's keys:** `background_tasks`, `cwd`, `effort`, `hook_event_name`,
  `last_assistant_message`, `permission_mode`, `prompt_id`, `scratchpad_dir`, `session_crons`,
  `session_id`, `stop_hook_active`, `transcript_path`. There is no `turn_number` or
  `had_tool_use`, although the docs list them.
- **`background_tasks`** lists running tasks only, each with `id`, `type`, `status` and
  `description`, plus `command` for a shell task. A killed or finished task drops out, so the
  list can't show a kill. It also holds stale teammates from earlier in the session.
- **P-b, done.** A command stopped at its `timeout` gets a notification with `status: killed`,
  the summary "Background command \"<description>\" was stopped after reaching its background
  time limit", and the note quoted under the gap.
- **P-e, passed.** At the stop of the turn the kill notice started, the notice is already in
  the transcript. It's an entry with `type: "user"` and `origin: {"kind": "task-notification",
  "producer": "session-task"}`, holding the `<task-id>`, `<status>killed</status>` and the
  summary. A `queue-operation` entry sits beside it.
- **P-c, answered by the docs.**
  - "An excluded command goes through the regular permission flow", and an allow rule covers it.
  - Auto mode keeps a narrow rule like `Bash(delegation-ledger wait *)` and sends the rest to its
    classifier.
  - `$(...)`, `cd` or a redirect keeps a call sandboxed, so the waiter must be launched bare.
  - T4 checks the rule live.
- **P-d, done.** `CLAUDE_CODE_SESSION_ID` is set to the session id in Bash, inside the sandbox
  and outside it. `CLAUDE_PID` is set in both, too.

### T1: `delegation-ledger wait`
- **Files:**
  - `skills/delegation/scripts/delegation-ledger`: a new `wait` subcommand and its usage line;
  - `skills/delegation/scripts/delegation_common.py`: a new `write_json(path, obj)`;
  - `tests/delegation/test_wait.py`.
- **The watch file**, at `<ledger state>/watches/<id>.json`, holds:
  - `id`, `session_id`, `description`, `condition`, `created`;
  - `waiter_pid`, `waiter_start` (its `procStart`), `waiter_heartbeat`;
  - `state` (open, done, failed, stale, dropped or acknowledged), and `blocked_at`.
- **The session** comes from one parent walk (`claude_identity`), since both env vars are
  inherited: a tmux pane or a nested `claude -p` can carry another session's values.
  - The walk finds a Claude process (a `~/.claude/sessions/<pid>.json` naming that pid and its
    procStart). If `CLAUDE_PID` is that process, `CLAUDE_CODE_SESSION_ID` is the session: the
    process set it for this Bash call, and it follows a `/clear` (checked live 2026-10-02, a
    process whose id changed mid-life). Otherwise the file's `sessionId` is the session.
  - The walk finds nothing: the env counts only when `CLAUDE_PID` is an ancestor.
  - Otherwise the session is `unknown` and no Claude process is recorded.
- **It refuses to run sandboxed.** If `dc.pids_visible()` is false, it prints "run
  delegation-ledger wait as a bare command" and exits 2 before recording anything.
- **What it waits for** (at least one):
  - `--pid N` (repeatable): done when all have exited;
  - `--file PATH`: done when it exists;
  - `--log PATH --done RE [--fail RE]`: a fail match makes exit 1;
  - `--stale MIN`: exit 2 when the log hasn't changed for that long;
  - `--codex RUN_ID`: done when the Codex pid is gone (`dc.codex_state`). The waiter then runs
    `codex-delegate finalize <run_id>` itself, with a fixed argv, and passes its output on.
    `finalize` is idempotent.
- **No arbitrary `--cmd`.** It would run unsandboxed, so it would be a sandbox escape.
- **Its limit:** `--max MIN` (default and maximum 110, which leaves room for a 5-minute finalize
  under the 120-minute cap; fractions allowed for tests). It polls every 15 s and updates the
  heartbeat on each poll, including while a finalize runs.
- **Pids it refuses:** pid 1, a kernel thread, another user's process, and one that isn't
  running. A sandboxed command's pids start near 1, and on the host those are root daemons.
  Each watched pid records its `comm`, so a wrong pid is visible.
- **One watch per Codex run:** a second `wait --codex` on a run that already has an open watch
  is refused, with that watch's `--resume` command.
- **Exits** (0 must only ever mean the job finished, since the lead reads the notification):
  - 0 when done;
  - 1 when the job failed: a `--fail` match, a pid exited with another condition unmet, or a
    codex stop row with a nonzero `exit`;
  - 2 when the log goes stale;
  - 3 when this waiter stepped aside: the watch was taken over by `--resume`, dropped, or its
    file is gone;
  - 64 on bad usage: an unknown id, no condition, a sandboxed call, a `--pid` that isn't running
    at the start (a pid echoed from a sandboxed command is from another PID namespace), or a
    resume of an ended watch;
  - 70 on an internal error;
  - 75 at `--max`, printing one line: `still running: re-arm with delegation-ledger wait --resume
    <id> (run_in_background, timeout 7200000)`.
- **Matching a log:** only complete lines count. A final unterminated line counts once the
  watched pids are gone, or once the log hasn't grown for one poll.
- **Pruning:** at start, it removes temp files older than a day and ended watches older than 7
  days.
- **`dc.pid_alive`** treats a zombie (state Z or X in `/proc/<pid>/stat`) as gone.
- **`--resume <id>`** reloads the condition, takes over as the waiter and clears `blocked_at`.
  **`--drop <id>`** marks the watch dropped.
- **Watch ids** pass a basename guard. Writes are atomic, and errors go to
  `delegation-ledger.err`.
- **`watch` and `open`** print open watches as a separate block after the delegations, and only
  when there are any. So `watch --summary` and the pinned "no live delegations" text don't
  change.
- **Verify:** unit tests for each condition, each exit code, the re-arm line, resume, drop, the
  heartbeat, and the sandbox refusal.
  - Copy `LedgerEnv` and `LiveSession` from `test_ledger.py`.
  - A real `Popen` child stands in for the job.
  - Use fractional `--max`.
- **Depends on:** T0.

### T2: The watch guard (a Stop hook)
- **Files:**
  - `hooks/watch-guard.sh`. It skips a payload with `agent_id`, then runs the script with
    `2>/dev/null; exit 0`. `setup.sh` links `hooks/*.sh` by glob, so setup needs no edit;
  - `skills/delegation/scripts/watch-guard`;
  - a third `Stop` group in `settings.json`, with timeout 5;
  - `tests/delegation/test_watch_guard.py`, and a wiring test in `test_settings.py`.
- **Watches.** For each watch of the payload's session that is in state open:
  1. Re-check its condition. If it's met and its waiter is alive, allow; the waiter records it.
     If it's met and the waiter is dead, no notification came, so it's an item in this stop's
     block ("<condition> is met, but its waiter had stopped, so no notification came. Check the
     result and report it."), recorded done at the same time.
  2. If its waiter is alive (pid plus `procStart`, and a heartbeat younger than 2 polls), allow.
     A shell task in `background_tasks` whose command holds the watch id also counts.
  3. Otherwise it has lapsed:
     - with no `blocked_at`, set it and block, with this reason: "Watch <id> (<desc>) has no
       live waiter and <condition> is unmet. If a command was stopped at its time limit, don't
       re-run it. Re-arm the watch: `delegation-ledger wait --resume <id>`, with
       `run_in_background` and `timeout: 7200000`. To stop watching it: `delegation-ledger wait
       --drop <id>`.";
     - with `blocked_at` set, allow, record the watch as acknowledged, and print a
       `systemMessage` warning.
- **The kill catch (T2b):**
  - **Finding kills:** read the last 256 KB of `transcript_path`, and parse each line. A kill is
    an entry with `origin.kind == "task-notification"` whose text holds `<status>killed</status>`
    and "background time limit". Take its `<task-id>` and its summary.
  - **Once per task:** each killed task blocks one stop, recorded in
    `<state>/kills/<session_id>.json` with a `since` time. On the guard's first run in a
    session, `since` is set 10 minutes back, so kills from before the install don't block.
  - **Mapping a kill to its command:** the notice's `<tool-use-id>` names the Bash `tool_use`
    that launched it, whose `input.command` is the command. Its result also carries
    `toolUseResult.backgroundTaskId`. The launch can be hours back, so the guard searches the
    whole file for that id, and only when there's a new kill.
  - **No double block:** a stop blocks at most once, with one reason that lists every new
    lapse and every new kill, and all of them are recorded together. The next stop goes
    through. A kill notice carries the Bash description, not the command, so to tell a killed
    waiter from a killed job, map the `<task-id>` to its command through the transcript (the
    tool result "running in background with ID: <task-id>" and its `tool_use` input). A killed
    `delegation-ledger wait` or `codex-delegate` folds into its watch's item.
  - **Codex watches:** a `watch_verdict` of done for a codex watch means Codex ended, but its
    finalize is still owed. The guard never records it as done; it sends the lead to `--resume`,
    whose waiter finalizes.
  - **The reason:** "Background command <description> was stopped at its time limit. If it was
    waiting on a job that's still running, don't re-run it: wait with `delegation-ledger wait`
    (`--pid`, `--file` or `--log`), with `run_in_background` and `timeout: 7200000`. If it was
    the job itself, report that it was stopped. If you've already handled it, end your turn."
- **Two phases, so a timeout loses nothing.** The guard first gathers every item read-only,
  within a 3 s budget: verdicts, the transcript scan, the launch lookups, the log tails. It then
  records them all in one quick locked pass, and prints. Lock waits are bounded by the same
  deadline, and the kill record's lock is per session. The scan has no size cap: a byte search
  for `task-notification` picks the lines worth parsing.
- **Acknowledging a lapse:** on a stop after the block, never on the stop that blocked.
  - Stops are told apart by a digest of the payload's `prompt_id` and
    `last_assistant_message` (`blocked_stop`), which twin guards receive identically, not by
    elapsed time.
  - The transcript's size (`blocked_size`) is the fallback when the payload lacks both, since
    it can grow between twins.
- **One failed write skips only its own watch:** the commit pass catches errors per item.
- **The whole-branch review's changes:**
  - a watch whose session is gone is orphaned even while its waiter lives, and `--resume` can
    take it over then;
  - the waiter prints a launch line with its watch id, and a new `wait` on an equal condition
    takes over the unresolved watch instead of making a second one;
  - each watch records its Claude Code process, so after `/clear` (a new session id in the same
    process) the guard adopts it;
  - a Codex run that never started is a failure, not undecidable, so its watch closes;
  - the hook shim logs Python's errors instead of dropping them, and the quick canary runs the
    installed shim;
  - the upgrade nudge names the manual re-arm check.
- **`--resume` doesn't take a watch from a live waiter**, and a caller with no Claude Code
  session keeps the watch's existing session.
- **Fail-open, per item.** An error on one watch or one kill (for example `dc.Undecidable`, when
  a codex run has left the ledger) skips that item and logs it. It doesn't skip the others. Any
  other exception means exit 0, and the error goes to `delegation-ledger.err`.
- **Reuse T1's helpers:** `dc.all_watches`, `dc.watch_verdict`, `dc.waiter_alive` and
  `dc.condition_text`. Write only through `dc.update_watch`.
- **Verify:** unit tests for these cases:
  - no state dir; no watches; another session's watch;
  - a live waiter; a met condition;
  - a lapse, which blocks; a second stop on the same lapse, which allows and warns;
  - a doubled guard, which blocks once;
  - a dropped watch;
  - a killed task, which blocks once and then allows;
  - a killed waiter of a recorded watch, which blocks once, not twice;
  - another session's kill, which is ignored;
  - a malformed payload, which allows.
- **Depends on:** T1.

### T3: Codex records its own watch
- **Files:**
  - `skills/delegation/scripts/codex-delegate`;
  - `skills/delegation/SKILL.md` §5;
  - `tests/delegation/test_codex_delegate.py`.
- **The change:**
  - **A launch line:** `run` and `resume` print one flushed line with the run id and the watch
    id, after the `pending` row and before the `Popen`. Today the run id prints only after Codex
    ends.
  - **The watch:** they record a `--codex <run_id>` watch whose waiter is the wrapper's own pid.
    The ledger's `wrapper_pid` isn't used, because it's stale on a resume until
    `thread.started`.
  - **`--max-wait MIN`** (default 110): the wrapper stops waiting and exits 75 with the re-arm
    line, leaving Codex running. Launched with `timeout: 7200000`, it never reaches the cap. If
    the lead forgot the timeout, the guard covers it.
  - **`status`:** passes `dc.pids_visible()` to `codex_state`, as `open` does.
  - **The resume window:** `resume` writes a row before its `Popen`. Today it writes nothing
    until `thread.started`, so a waiter started in between sees the old stop row and exits 0
    while Codex is running.
  - **`lookup`** reuses `dc.find_codex` (from T1), not a copy of it.
  - **Shared helpers:** the waiter's core moved into `delegation_common`, so the wrapper and
    `wait` share it: take, beat, end, the refusals, session resolution and the re-arm line.
  - **A `detached` row** is written at `--max-wait` with Codex's pid. Without it, a wrapper that
    left before `thread.started` would leave no pid, and the next waiter would finalize while
    Codex still ran.
  - **`finalize` refuses while the wrapper is alive**, and runs under the per-run lock. If the
    run has no thread id, it reads one from `events.jsonl`.
  - **A wrapper run inside the sandbox records no watch**, since its pids would be from another
    namespace. It says so on stderr.
  - **The guard folds a killed wrapper into its run's watch**, as it does a killed waiter.
  - **`finalize` takes a per-run lock** and re-checks for a stop row inside it. Without the
    lock, two finalizes of one run can both append a stop row:
    - a waiter SIGKILLed mid-finalize leaves its finalize child running, and a later waiter
      starts another;
    - a lead runs the `codex-delegate finalize` that `open` and `watch` suggest while a waiter is
      finalizing.

    (T1 refuses a second open watch on one run.)
  - **§5:**
    - launch with `run_in_background` and `timeout: 7200000`;
    - add exit 75 to the exit codes;
    - replace "the exit notification wakes you" with what happens past the cap.
- **Verify:**
  - a `FullRun` test that a run records the watch and prints the launch line;
  - a test that `--max-wait` exits 75 while the fake Codex keeps running;
  - a test that the waiter finalizes;
  - a watch is a file, not a ledger row, so `test_clean_run`'s pinned `pending, start, stop`
    holds.
- **Depends on:** T1, T2.
- **Live result (2026-10-02, 2.1.286): a killed wrapper takes Codex with it.**
  - **The run:** a Terra job (a 90 s sleep) launched with `timeout: 60000` died with its wrapper.
    `status` said "codex pid gone, wrapper gone". The guard folded the kill into the watch and
    blocked once, and the re-arm finalized the run (exit 4, no report) with no status call. So
    nothing went silent, but the work was lost.
  - **Codex writes only to files** (stdout to `events.jsonl`, stderr to `stderr.log`, stdin closed
    after the prompt), so it isn't a broken pipe.
  - **A probe settled the cause.** Claude Code's time-limit kill takes the command's whole
    descendant tree: a `start_new_session` child died with its parent. A double-forked child,
    reparented away (to WSL's init relay, pid 553), survived.
  - **A normal exit is safe.** A `start_new_session` child outlived its parent's normal exit, and
    was adopted by pid 553, so Claude Code isn't a subreaper. The `--max-wait` exit 75 therefore
    leaves Codex running, as designed.
  - **False claims:** the launch line's "If this command is stopped, Codex keeps running", and
    SKILL §5's "If the wrapper does get killed anyway, Codex keeps running". The second was
    false before this branch too.
- **Decision (Hayden, 2026-10-02): detach Codex.**
  - **The supervisor:** a double-forked process runs Codex, writes `codex.pid` and then
    `codex.rc`, and the wrapper polls for them. A killed wrapper leaves Codex running, and the
    re-arm finalizes the full result.
  - **Stopping on purpose:** `codex-delegate cancel <run_id>` replaces stopping the background
    task.
  - **Rejected, keep it coupled and fix the claims:** a short timeout, or quitting Claude Code,
    would lose the run's work.
  - **The cost:** it relies on Claude Code killing by process tree, not by session, process group
    or cgroup. A dated `due.toml` check reruns the kill probe after upgrades.
- **A codex run that ended unfinalized stays open.** Its watch isn't recorded `done`, since the
  outcome is unknown until finalize, and `done` would make `--resume` refuse it. A marker makes
  the guard block once on "re-arm to finalize", and the re-arm delivers the summary.

### T4: The allow rule, and crash recovery
- **Files:**
  - `settings.json`, edited by the lead, since a writer can't write it;
  - `skills/delegation/scripts/delegation_checks.py`;
  - `docs/delegation.md`'s install section.
- **The change:**
  - **The allow rule:** the baseline gains `permissions.allow: ["Bash(delegation-ledger wait
    *)"]`.
    - `setup.sh` replaces a live `permissions` object with the baseline's, and says so on
      stderr. So the install notes say personal rules go in `settings.machine.json`.
    - On the machine that planned this (2026-10-02), neither the live file nor the overlay had a
      `permissions` object.
  - **Crash recovery:** a new nudge in `delegation_checks.evaluate` lists open watches whose
    session is gone, with the `wait --resume` command. It joins the numbered session-start
    `systemMessage`.
- **Verify:**
  - `tests/setup` still passes;
  - a watch left by a killed session shows in `evaluate`'s output;
  - live, `claude -p --permission-mode default` runs `delegation-ledger wait --file <existing>`
    with the rule, and is refused without it.
- **Depends on:** T1.

### T5: The docs and the one CLAUDE.md line
- **Files:**
  - `docs/delegation.md`: a "Long waits" section, the T0 results under the verified facts (with
    the version), and rows in "What ships";
  - `skills/delegation/SKILL.md` §4;
  - `README.md`, if new files ship;
  - `CLAUDE.md`, through `/revise-claude-md` with Hayden's approval. The line: "A wait that may
    outlast 30 minutes goes through `delegation-ledger wait`: Bash background commands stop at 30
    minutes by default and 2 hours at most, Monitor at 30."
- **Verify:** a fresh `reviewer` checks the docs against the code.
- **Depends on:** T1 to T4.

### T6: A live re-arm case and the canary
- **Files:**
  - `tests/delegation/run.py`, for a `rearm` case;
  - the canary's list of binary strings.
- **The change:**
  1. A background `sleep 90` job, then `delegation-ledger wait --pid <pid> --max 0.33` launched
     with `timeout: 30000`.
  2. Expect a waiter exit of 75, a block from the guard, and a re-arm. Then the job ends, the
     waiter exits 0, and the agent reports.
  3. `-p` kills background shells about 5 s after its final result, so if it can't host this,
     make it a dated manual check in `due.toml` instead.
  4. Add the strings the guard depends on to the canary's binary strings: the note's "do not
     restart it", "background time limit", and `task-notification`.
- **Verify:** the transcript shows a re-arm and a final done, with no human input.
- **Depends on:** T1 to T3.

## Verification target (whole feature)

The feature is done when all of these hold:
- **Unit suites:** green (`python3 -m unittest discover -s tests/delegation -t
  tests/delegation`, and `tests/setup`).
- **Live waits in an interactive session:**
  - a waiter exits 75;
  - ending the turn without a re-arm is blocked once;
  - the re-armed waiter exits 0.
- **The live kill catch:** a plain background sleep killed at a 15 s timeout gets its stop blocked
  once.
- **Codex:** a hand-run job launched with a short Bash timeout is finalized without anyone asking
  for status.
- **The `rearm` case:** it passes, or its manual check does.
