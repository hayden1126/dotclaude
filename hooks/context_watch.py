"""context-watch: tell the session to hand off (the pass skill) before auto-compact.

hooks/context-watch.sh runs this file with python3 -I on Stop and PostToolUse, passing the event
on stdin. It prints at most one JSON object and fails open: any error says nothing. Tests import
it (tests/setup/test_context_watch.py). Stdlib only; keep the source ASCII. PLAN.md "PR 4:
auto-pass" has the design; hooks/autopass_state.py has the tiers and decide().

Skipped: a subagent's event (agent_id) and a session id that isn't a plain name. A session with
CLAUDE_CODE_SESSION_ATTENDED=0 (`claude -p`, `claude --bg`) gets its count written but no nudge:
it has no pane to respawn, and `lane ls` still reads its count.

The count: the transcript's last main-chain assistant entry (type "assistant", not isSidechain)
with a message.usage, summed as input + cache read + cache creation tokens (spike A3: it matched
the statusline). A zero sum (a synthetic error entry) doesn't count. The last 512 KiB are read,
then once 8 MiB when no such entry is in them. Any miss says nothing and writes nothing. The
count is merged into ctx/<session>.json as {tokens, time} on every event, firing or not; a
`window` there (the model's context window, which the statusline widget writes) lowers the
tiers' window (autopass_state.window).

Crossings live in the watcher's own record, ctx-watch/<session>.json, not in stop_hook_active:
- only the highest tier the count has crossed may speak, once per crossing; when it speaks, the
  tiers under it count as fired too, so a lower one never speaks after a higher one;
- a count more than 50000 under a tier re-arms it (a compact drops the count; a new session id
  is a new record), so a count hovering at a tier never fires it twice;
- the hard tier also re-arms 20000 tokens past its last firing, unless the transcript shows,
  after that firing (the record keeps its time and the transcript's size then), a main-chain
  tool call that starts the handoff: the Skill tool with skill `pass` or `handoff`, or a Bash
  command running `pass-respawn`. A handoff costs 22k to 47k, so the re-arm would otherwise
  say "hand off now" in the middle of the handoff it asked for.

On (decide()): soft speaks on Stop only, as a block. Wrap-up and hard speak on Stop as a block
and on PostToolUse as additionalContext; one that spoke on PostToolUse doesn't repeat at the Stop.
Off: only the hard tier, once per crossing (no +20k re-arm), as a user-only systemMessage, on
whichever event comes first.

Background work, two rules:
- busy: a task of stop_ring.WAITS (a subagent, shell, workflow or cloud session: work whose
  result the turn waits on). Soft and wrap-up stay quiet and stay armed; hard says its busy
  variant (pass compact: a compact keeps the tasks alive).
- blocked: any task a plain pass would be refused for (lanelib.plain_pass_blockers, the rule
  pass-respawn uses: everything but `dream`, monitors and teammates too). Every tier then says to
  pass in compact mode.
On Stop the payload's background_tasks decide. PostToolUse has no task list, so the session's
stop record (stops/<session>.json, which stop-ring.sh writes at every Stop) decides when it was
written within the last 10 minutes: its `waits` for busy, its `tasks` for blocked. With no such
record the state is unknown and counts as blocked: compact mode is always safe, and a plain
pass would be refused if a monitor or teammate runs. A task started since the last Stop isn't
seen.

Nothing fires while a pass is already pending for the session (pass-respawn's waiter holds
pass-pending/<session>.lock): the turn should end so the pass can act.

decide() runs git and tmux, so it runs only when a tier would fire, before the session's lock
(ctx-watch/<session>.lock) is taken, and its answer is cached in the record for 60 s (/autopass
clears the cache for its session). Under the lock the record is re-read, stepped and written.
"""
import copy
import fcntl
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import autopass_state as aps  # noqa: E402
import stop_ring  # noqa: E402

TAIL, WIDE = 512 * 1024, 8 * 1024 * 1024
REARM = 20000
HYSTERESIS = 50000
STOP_FRESH = 600
MODE_TTL = 60
HANDOFF_SKILLS = ("pass", "handoff")


LEAD = "[autopass] Context is at {n}, auto-compact near {c}"
COMPACT_WHY = "(a compact keeps background tasks alive; a plain pass would be refused)"
TEXTS = {
    "soft": LEAD + ". If the task is done end to end, run the pass skill now. If only a small "
                   "remainder is left, finish it first. If your last reply asked Hayden "
                   "something, end your turn without doing anything.",
    "wrap": LEAD + ". Finish the step you are on and don't start another. If more than this "
                   "step is left, run the pass skill now (compact mode if you are mid-task).",
    "hard": LEAD + ": hand off now. Run the pass skill: compact mode mid-task, plain at a task "
                   "boundary.",
    "hard_busy": LEAD + ", and background work is running: run the pass skill in compact mode "
                        "now (a compact keeps background tasks alive).",
    "soft_compact": LEAD + ". If the task is done end to end, run the pass skill in compact "
                           "mode now " + COMPACT_WHY + ". If only a small remainder is left, "
                           "finish it first. If your last reply asked Hayden something, end "
                           "your turn without doing anything.",
    "wrap_compact": LEAD + ". Finish the step you are on and don't start another. If more than "
                           "this step is left, run the pass skill in compact mode now "
                           + COMPACT_WHY + ".",
    "hard_compact": LEAD + ": hand off now. Run the pass skill in compact mode " + COMPACT_WHY
                         + ".",
    "off": "Context {n}, auto-compact near {c}: hand off now (/pass).",
    "off_compact": "Context {n}, auto-compact near {c}: hand off now (/pass compact: background "
                   "tasks are running).",
}


def usage_total(line: bytes):
    """The context size an assistant transcript line records, or None."""
    if b'"assistant"' not in line:
        return None
    try:
        d = json.loads(line)
    except ValueError:
        return None
    if not isinstance(d, dict) or d.get("type") != "assistant" or d.get("isSidechain"):
        return None
    msg = d.get("message")
    u = msg.get("usage") if isinstance(msg, dict) else None
    if not isinstance(u, dict):
        return None
    parts = [u.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens",
                                   "cache_creation_input_tokens")]
    if not all(aps.is_int(p) and p >= 0 for p in parts) or not sum(parts):
        return None
    return sum(parts)


def tokens(path) -> int | None:
    """The last main-chain assistant usage in the transcript at path, or None."""
    if not isinstance(path, str) or not path:
        return None
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            for span in (TAIL, WIDE):
                f.seek(max(0, size - span))
                lines = f.read(span).split(b"\n")
                if size > span:
                    lines = lines[1:]  # the first line is cut
                for line in reversed(lines):
                    n = usage_total(line)
                    if n is not None:
                        return n
                if size <= span:
                    return None
    except OSError:
        return None
    return None


def starts_handoff(line: bytes) -> bool:
    """Whether a transcript line is a main-chain assistant tool call that starts a handoff."""
    if b'"tool_use"' not in line or not (b'"Skill"' in line or b"pass-respawn" in line):
        return False
    try:
        d = json.loads(line)
    except ValueError:
        return False
    if not isinstance(d, dict) or d.get("type") != "assistant" or d.get("isSidechain"):
        return False
    msg = d.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    for c in content if isinstance(content, list) else []:
        if not isinstance(c, dict) or c.get("type") != "tool_use":
            continue
        args = c.get("input") if isinstance(c.get("input"), dict) else {}
        if c.get("name") == "Skill" and args.get("skill") in HANDOFF_SKILLS:
            return True
        if c.get("name") == "Bash" and isinstance(args.get("command"), str) \
                and "pass-respawn" in args["command"]:
            return True
    return False


def handoff_since(path, offset) -> bool:
    """Whether the transcript gained a handoff-starting call past byte offset (its last WIDE
    bytes at most)."""
    if not isinstance(path, str) or not aps.is_int(offset):
        return False
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            start = max(offset, size - WIDE)
            f.seek(start)
            lines = f.read(size - start).split(b"\n")
    except OSError:
        return False
    return any(starts_handoff(line) for line in lines)


def num(v):
    return v if aps.is_int(v) else None


def fresh_record(rec) -> dict:
    rec = rec if isinstance(rec, dict) else {}
    fired = rec.get("fired") if isinstance(rec.get("fired"), dict) else {}
    out = {"fired": {t: num(fired.get(t)) for t in aps.TIER_NAMES},
           "off_hard": num(rec.get("off_hard")),
           "hard_time": rec.get("hard_time") if isinstance(rec.get("hard_time"), float) else None,
           "hard_offset": num(rec.get("hard_offset")),
           "handing_off": rec.get("handing_off") is True}
    if isinstance(rec.get("mode"), dict):
        out["mode"] = rec["mode"]
    return out


def rearm(rec: dict, n: int, tiers: dict) -> None:
    """A count more than HYSTERESIS under a tier re-arms it."""
    for t in aps.TIER_NAMES:
        if n < tiers[t] - HYSTERESIS:
            rec["fired"][t] = None
    if n < tiers["hard"] - HYSTERESIS:
        rec["off_hard"] = None
        rec.update(hard_time=None, hard_offset=None, handing_off=False)


def top_tier(n: int, tiers: dict):
    for t in reversed(aps.TIER_NAMES):
        if n >= tiers[t]:
            return t
    return None


def armed(rec: dict, tier: str, n: int, handoff) -> bool:
    """Whether tier may fire at n. handoff(offset) -> whether a handoff started past it; asked
    only for the hard tier's +REARM re-arm, and remembered once true."""
    last = rec["fired"][tier]
    if last is None:
        return True
    if tier != "hard" or n < last + REARM or rec["handing_off"]:
        return False
    if handoff(rec["hard_offset"]):
        rec["handing_off"] = True
        return False
    return True


def due(rec: dict, n: int, tiers: dict, event: str, handoff):
    """(top tier, whether it is due with autopass on, whether the off line is due), after the
    re-arm, which changes rec in place."""
    rearm(rec, n, tiers)
    top = top_tier(n, tiers)
    on_due = top is not None and (event == "Stop" or top != "soft") \
        and armed(rec, top, n, handoff)
    off_due = n >= tiers["hard"] and rec["off_hard"] is None
    return top, on_due, off_due


def step(rec: dict, n: int, tiers: dict, event: str, mode, work, handoff=lambda o: False,
         size=None, now=None):
    """What this event says: (text key or None, "block" | "context" | "system" | None), with
    rec updated in place. mode() -> on (True or False, or None: say nothing and mark nothing),
    work() -> "busy" | "blocked" | None, both run only when something would fire. size is the
    transcript's size now, kept with a hard firing for the handoff check."""
    top, on_due, off_due = due(rec, n, tiers, event, handoff)
    if not (on_due or off_due):
        return None, None
    on = mode()
    if on is None:
        return None, None
    if on:
        if not on_due:
            return None, None
        state = work()
        if state == "busy":
            if top != "hard":
                return None, None
            key = "hard_busy"
            rec["fired"]["hard"] = n
        else:
            key = top + ("_compact" if state == "blocked" else "")
            for t in aps.TIER_NAMES:
                if n >= tiers[t]:
                    rec["fired"][t] = n
        if top == "hard":
            rec.update(hard_time=float(now if now is not None else time.time()),
                       hard_offset=size if aps.is_int(size) else None, handing_off=False)
        return key, ("block" if event == "Stop" else "context")
    if not off_due:
        return None, None
    rec["off_hard"] = n
    return ("off_compact" if work() else "off"), "system"


def labels(tasks) -> list:
    """background_tasks as stop-ring.sh records them: each type, `unlabeled` for none."""
    return [t.get("type") if isinstance(t, dict) and isinstance(t.get("type"), str)
            and t.get("type") else "unlabeled" for t in tasks] if isinstance(tasks, list) else []


def work_state(waits: list, tasks: list):
    if any(w in stop_ring.WAITS for w in waits if isinstance(w, str)):
        return "busy"
    lib = aps.lanelib()
    blockers = lib.plain_pass_blockers(tasks) if lib else [t for t in tasks if t != "dream"]
    return "blocked" if blockers else None


def stop_work(d: dict):
    tasks = labels(d.get("background_tasks"))
    return work_state(tasks, tasks)


def recorded_work(sid: str):
    """The stop record's work state when it is under STOP_FRESH seconds old. Without one the
    state is unknown, which counts as "blocked": compact mode is always safe."""
    rec = aps.load_json(os.path.join(aps.state_dir(), "stops", sid + ".json"))
    when = rec.get("time") if isinstance(rec, dict) else None
    if not isinstance(when, (int, float)) or not 0 <= time.time() - when < STOP_FRESH:
        return "blocked"
    waits = rec.get("waits") if isinstance(rec.get("waits"), list) else []
    tasks = rec.get("tasks")
    return work_state(waits, tasks if isinstance(tasks, list) else ["?"])


def pass_pending(sid: str) -> bool:
    """Whether pass-respawn's waiter holds this session's pending lock."""
    try:
        fd = os.open(os.path.join(aps.state_dir(), "pass-pending", sid + ".lock"), os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def cached_mode(rec: dict, cwd, pane):
    """(on, a fresh cache entry to store, or None when the cached one served)."""
    m = rec.get("mode")
    now = time.time()
    if (isinstance(m, dict) and isinstance(m.get("on"), bool)
            and isinstance(m.get("at"), (int, float)) and 0 <= now - m["at"] < MODE_TTL):
        return m["on"], None
    on, source = aps.decide(cwd, pane)
    return on, {"on": on, "source": source, "at": now}


def render(key: str, kind: str, n: int, tiers: dict) -> dict:
    text = TEXTS[key].format(n=aps.kilo(n), c=aps.kilo(tiers["compact_at"]))
    if kind == "block":
        return {"decision": "block", "reason": text}
    if kind == "context":
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                       "additionalContext": text}}
    return {"systemMessage": text}


def prune_locks(directory: str, now: float) -> None:
    """Delete the directory's *.lock files older than stop_ring.PRUNE_AGE, once a day."""
    stamp = os.path.join(directory, ".pruned-locks")
    try:
        if now - os.path.getmtime(stamp) < stop_ring.PRUNE_EVERY:
            return
    except OSError:
        pass
    try:
        with open(stamp, "a"):
            pass
        os.utime(stamp, (now, now))
    except OSError:
        return
    for path in glob.glob(os.path.join(directory, "*.lock")):
        try:
            if now - os.path.getmtime(path) > stop_ring.PRUNE_AGE:
                os.unlink(path)
        except OSError:
            pass


def handle(d: dict, pane=None):
    """The output object for event d, or None. Writes ctx/ and ctx-watch/."""
    if d.get("agent_id"):
        return None
    event, sid = d.get("hook_event_name"), d.get("session_id")
    if event not in ("Stop", "PostToolUse") or not isinstance(sid, str) \
            or not stop_ring.SID.fullmatch(sid):
        return None
    path = d.get("transcript_path")
    n = tokens(path)
    if n is None:
        return None
    now = time.time()
    ctx = aps.write_ctx(sid, n, now)
    stop_ring.prune(os.path.dirname(aps.ctx_path(sid)), now)
    if os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "0":
        return None
    tiers = aps.tiers(aps.window(path, ctx.get("window")))
    if tiers is None:
        return None
    try:
        size = os.path.getsize(path)
    except (OSError, TypeError, ValueError):
        size = None
    seen = {}

    def handoff(offset):
        if offset not in seen:
            seen[offset] = handoff_since(path, offset)
        return seen[offset]

    # decide() (git, tmux) before the lock, on a dry run of the record.
    watch = aps.watch_path(sid)
    before = fresh_record(aps.load_json(watch))
    _, on_due, off_due = due(copy.deepcopy(before), n, tiers, event, handoff)
    on, entry = None, None
    if (on_due or off_due) and not pass_pending(sid):
        on, entry = cached_mode(before, d.get("cwd"), pane)

    def work():
        return stop_work(d) if event == "Stop" else recorded_work(sid)

    with aps.watch_lock(sid) as locked:
        if not locked:
            return None
        rec = fresh_record(aps.load_json(watch))
        if entry is not None:
            rec["mode"] = entry
        key, kind = step(rec, n, tiers, event, lambda: on, work, handoff, size, now)
        aps.write_json(watch, rec)
    prune_locks(os.path.dirname(watch), now)
    stop_ring.prune(os.path.dirname(watch), now)
    return render(key, kind, n, tiers) if key else None


def main() -> None:
    try:
        d = json.load(sys.stdin.buffer)
        out = handle(d, os.environ.get("TMUX_PANE")) if isinstance(d, dict) else None
    except Exception:
        return
    if out:
        sys.stdout.write(json.dumps(out))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
