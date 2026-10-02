# PLAN: re-arm long background waits (the watch guard)

> Written 2026-10-02 for a fresh implementer. The planner is not the implementer.

## Approach

**The gap.**
- A Bash command run with `run_in_background` is stopped at its timeout (30 minutes by default,
  2 hours at most), and Claude Code then wakes the agent once. A `Monitor` watch stops at 30
  minutes. Both specs come from the tool descriptions.
- On 2026-10-02 a main-thread agent watching a long detached job hit the 2-hour cap. It read "the
  longest allowed" as the end of the watch and ended its turn. Nothing woke it when the job
  finished.
- Monitor's spec says to re-arm at expiry. The Bash spec doesn't, so nothing in the agent's view
  told it to.

**The same gap in dotclaude's own Codex flow.**
- SKILL §5 says to launch `codex-delegate run` with `run_in_background`, and that "the exit
  notification wakes you".
- The wrapper's own `--timeout` defaults to 3h, and §5 never says to pass the Bash `timeout`. So
  the wrapper is stopped at 30 minutes, or at 2 hours with the timeout set. Codex keeps running,
  and nothing wakes the lead when it ends.

**The fix is enforcement, not prose.** Waiting is liveness, which the delegation design's rule
puts on the machine. The pieces:
1. A waiter, `delegation-ledger wait`:
   - it records a *watch*;
   - it exits before the cap with the exact re-arm command;
   - it runs outside the sandbox (the ledger is already in `excludedCommands`), because every
     sandboxed command gets its own PID namespace and can't see processes started elsewhere.
2. A main-thread Stop hook, the *watch guard*. It blocks a turn from ending while one of the
   session's watches has lapsed: the condition is unmet and no waiter is alive.
3. `codex-delegate` records its own watch.
4. An allow rule, so a re-arm never stops at a permission prompt.

**Why C over the alternatives** (evaluated 2026-10-02 against every situation found):
- **Prose alone (A)** relies on the judgment that already failed.
- **A waiter with no hook (B)** improves the odds, but it still asks.
- **A `CronCreate` heartbeat (D)** is rejected:
  - its jobs live only in the session, so a restart loses them;
  - each poll costs a turn;
  - the agent has to create it, which is prose again;
  - a forgotten job fires for 7 days.
- **D adds nothing C lacks.** Every way a waiter can end wakes the agent: done, failed, at the cap,
  or killed. The stop that follows runs the guard.

**Decisions taken:**
- **Option C:** Hayden chose it.
- **How hard the guard pushes: block once per lapse.** This was recommended; Hayden deferred to the
  evaluation.
  - It blocks the first stop with the re-arm command.
  - When Claude Code sets `stop_hook_active` on the next stop, the guard lets it through, warns,
    and records the lapse as acknowledged.
  - Blocking until a drop would wedge the session on a broken waiter, or on a re-arm stuck at a
    permission prompt.

**Out of scope:**
- Subagents. BRIEF forbids ending a turn while a background command runs, and the deadlines
  (`policy.toml` `[deadline]`, 60-minute stop at most) cap them well under 2 hours.
- Teammates.

**Reuse:**
- the ledger's state dir and helpers (`skills/delegation/scripts/delegation_common.py`);
- the session-from-pid rule that `delegation-ledger open` uses (`~/.claude/sessions/<pid>.json`
  plus `/proc`);
- `codex-delegate status` for a Codex run's state;
- the live harness, `tests/delegation/run.py`.

## Tasks (bite-sized, ordered, independently verifiable)

### T0: Probe the assumptions C rests on (a gate)
- Files: none committed. Results go in `docs/delegation.md`'s verified facts, dated, with the
  Claude Code version.
- Change: four probes.
  - **P-a.** In an interactive session (not `-p`, whose handling of background notifications is
    unverified), install a temporary Stop hook that logs its payload and blocks once while a marker
    file exists. Run `sleep 20` with `run_in_background`. Check:
    - the hook fires on the turn the completion notice starts;
    - `{"decision": "block", "reason": ...}` makes the agent continue;
    - the next stop carries `stop_hook_active: true`.

    Record the payload's fields (`session_id`, `transcript_path`, `stop_hook_active`).
  - **P-b.** Run `sleep 60` with `run_in_background` and `timeout: 15000`. Record what the agent
    sees when the tool stops it (status and text).
  - **P-c.** With `Bash(delegation-ledger wait *)` in `permissions.allow`, check that the excluded
    command runs without a prompt in default mode. Note auto mode's behavior too.
  - **P-d.** Check whether Bash commands get a session-id env var. If not, the waiter resolves its
    session through its ancestor pids.
- Verify: each probe's result is written down. **If P-a fails, stop and tell Hayden.** The fallback
  is B plus a session-start notice, and Hayden decides.
- Depends on: none.

### T1: `delegation-ledger wait`
- Files: `skills/delegation/scripts/delegation-ledger` (a new `wait` subcommand), and
  `tests/delegation/test_wait.py`.
- **Watch file:** `<ledger state>/watches/<id>.json` holds:
  - `id`, `session_id`, `description`, `condition`, `created`;
  - `waiter_pid`, `waiter_heartbeat`;
  - `state`: open, done, failed, stale, dropped or acknowledged.
- **What it waits for** (at least one):
  - `--pid N` (repeatable): done when all have exited;
  - `--file PATH`: done when it exists;
  - `--log PATH --done RE [--fail RE]`: a fail match makes exit 1;
  - `--stale MIN`: exit 2 when the log hasn't changed for that long;
  - `--codex RUN_ID`: done when `codex-delegate status` reports the run ended.
- **No arbitrary `--cmd`.** It would run unsandboxed, so it would be a sandbox escape.
- **Its limit:** `--max MIN` (default 110, under the 120-minute cap; fractions allowed for tests).
  It polls every 15 s.
- **Exits:**
  - 0 when done;
  - 1 when it fails;
  - 2 when the log goes stale;
  - 75 at `--max`, printing one line: `still running: re-arm with delegation-ledger wait --resume
    <id> (run_in_background, timeout 7200000)`.
- **`--resume <id>`** reloads the condition, and **`--drop <id>`** marks the watch dropped.
- **`watch` and `open`** list open watches beside the delegations.
- Verify: unit tests for each condition, each exit code, the re-arm line, resume, drop, and a
  heartbeat update. Use fractional `--max`.
- Depends on: T0 (P-d decides how the session is resolved).

### T2: The watch guard (a Stop hook)
- Files:
  - `hooks/watch-guard.sh`. Its bash fast path exits 0 when the watches dir is missing, so a
    session with no watches pays for one stat;
  - `skills/delegation/scripts/watch-guard`;
  - the `Stop` entry in `settings.json`;
  - the install line in `setup.sh` (follow how the other hooks are linked);
  - `tests/delegation/test_watch_guard.py`.
- Change. For the payload's session, take each watch in state open:
  1. Re-check its condition. If it's met, record done and allow.
  2. If its waiter is alive (pid plus a fresh heartbeat), allow.
  3. Otherwise it has lapsed:
     - without `stop_hook_active`, print `{"decision": "block", "reason": "Watch <id> (<desc>)
       lapsed while <condition> is still unmet. Re-arm: delegation-ledger wait --resume <id>,
       with run_in_background and timeout 7200000. Or drop it: delegation-ledger wait --drop
       <id>."}`;
     - with `stop_hook_active`, allow, record the lapse as acknowledged, and print a
       `systemMessage` warning.

  Any exception means exit 0: it fails open, and the error goes to the ledger log.
- Verify: unit tests for:
  - no dir; no watches; another session's watch;
  - a live waiter; a met condition;
  - a lapse, which blocks; a lapse with `stop_hook_active`, which allows and warns;
  - a dropped watch; a malformed payload, which allows.
- Depends on: T0 (P-a), T1.

### T3: Codex records its own watch
- Files: `skills/delegation/scripts/codex-delegate`, and `skills/delegation/SKILL.md` §5.
- Change:
  - `run` and `resume` record a `--codex <run_id>` watch, with the wrapper as its waiter. When
    the Bash cap stops the wrapper, the guard has the lead re-arm through `wait --resume`.
  - §5: launch with `run_in_background` and `timeout: 7200000`. Replace "the exit notification
    wakes you" with what happens past the cap.
- Verify:
  - a unit test that a run records the watch;
  - a hand check: a Codex run under a short Bash timeout makes the guard block, and the re-arm
    finishes the run.
- Depends on: T1, T2.

### T4: The allow rule, and crash recovery
- Files: `settings.json`, and `hooks/delegation-due.sh` (or the SessionStart path it uses).
- Change:
  - `permissions.allow` gains `Bash(delegation-ledger wait *)`, if P-c showed it's needed;
  - at session start, one line lists open watches whose session is gone, with the
    `wait --resume` command.
- Verify: `tests/setup` still passes. A watch left by a killed session shows at the next start.
- Depends on: T1.

### T5: The docs and the one CLAUDE.md line
- Files:
  - `docs/delegation.md`: a "Long waits" section; the probe results under the verified facts;
    rows in "What ships";
  - `skills/delegation/SKILL.md` §4;
  - `README.md`, if new files ship;
  - `CLAUDE.md`, through `/revise-claude-md` with Hayden's approval. The line: "A wait that may
    outlast 30 minutes goes through `delegation-ledger wait`: Bash background commands stop at 30
    minutes by default and 2 hours at most, Monitor at 30."
- Verify: a fresh `reviewer` checks the docs against the code.
- Depends on: T1 to T4.

### T6: A live re-arm case and the canary
- Files: `tests/delegation/run.py` (a `rearm` case), and the canary list.
- Change:
  1. A background `sleep 90` job, then `delegation-ledger wait --pid <pid> --max 0.33` launched
     with `timeout: 30000`.
  2. Expect a waiter exit of 75, a block from the guard, and a re-arm. Then the job ends, the
     waiter exits 0, and the agent reports.
  3. If `-p` can't host this (P-a), make it a dated manual check in `due.toml` instead.
- Verify: the transcript shows two or more re-arms and a final done, with no human input.
- Depends on: T1 to T3.

## Verification target (whole feature)

The feature is done when all of these hold:
- the unit suites are green (`python3 -m unittest discover -s tests/delegation -t
  tests/delegation`, and `tests/setup`);
- the `rearm` live case, or its manual check, passes;
- a hand-run Codex job over the Bash timeout is woken and finalized without anyone asking for
  status.
