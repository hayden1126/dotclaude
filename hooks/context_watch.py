"""context-watch: tell the session to hand off (the pass skill) before auto-compact.

hooks/context-watch.sh runs this file with python3 -I on Stop, PostToolUse and
SessionStart(compact), passing the event on stdin. It prints at most one JSON object and fails
open: any error says nothing. Tests import it (tests/setup/test_context_watch.py). Stdlib only;
keep the source ASCII. PLAN.md "PR 4: auto-pass" has the design; hooks/autopass_state.py has
the tiers and decide().

Skipped: a subagent's event (agent_id) and a session id that isn't a plain name. A session with
CLAUDE_CODE_SESSION_ATTENDED=0 (`claude -p`, `claude --bg`) gets its count written but no nudge:
it has no pane to respawn, and `lane ls` still reads its count.

The count: the transcript's last main-chain assistant entry (type "assistant", not isSidechain)
with a message.usage, summed as input + cache read + cache creation tokens (spike A3: it matched
the statusline). A zero sum (a synthetic error entry) doesn't count. A main-chain compact
boundary (a system entry, subtype compact_boundary) met before such an entry means no count yet:
the first reply after a compact can reach the transcript after its tool call's hook runs
(batched writes; session 89ae7cc8 counted the pre-compact 521k at a real 107k), and the
boundary's postTokens leaves out the system prompt and tools. SessionStart(compact) blanks the
ctx file's tokens (null), so `lane ls` and /autopass show no count until a real one lands; it
writes only tokens and time, and the next count re-arms the tiers it drops under. The last 512
KiB are read, then once 8 MiB when no such entry is in them. Any miss says nothing and writes
nothing. At a Stop the turn's final reply lands in the transcript about 100 ms into the hook
(spike A8), so while the last main-chain user or assistant entry is a user's (or none is in
reach), the watcher re-reads every 25 ms for up to STOP_WAIT (1.5 s); past that it logs a line
to stderr and uses the last count on disk, if any. The count is merged into ctx/<session>.json
as {tokens, time} on every event, firing or not; a `window` there (the model's context window,
which the statusline widget writes) lowers the tiers' window (autopass_state.window).

Crossings live in the watcher's own record, ctx-watch/<session>.json, not in stop_hook_active:
- only the highest tier the count has crossed may speak, once per crossing; when it speaks, the
  tiers under it count as fired too, so a lower one never speaks after a higher one;
- a count more than min(50000, tier // 4) under a tier re-arms it (a compact drops the count;
  a new session id is a new record), so a count hovering at a tier never fires it twice, and a
  small window's tiers still re-arm after a compact;
- the hard tier also re-arms min(20000, half the gap from hard to compact_at) past its last
  firing (20k at 600k), unless the transcript shows, after that firing (the record keeps its
  time and the transcript's size then), a main-chain tool call that starts the pass: the Skill
  tool with skill `pass`, a Bash command that starts with `pass-respawn` (after blanks and an
  optional `!`), or a typed `/pass` (a user entry whose text starts with Claude Code's
  <command-message> block and names <command-name>/pass</command-name>). A handoff costs 22k
  to 47k, so the re-arm would otherwise say "hand off now"
  in the middle of the pass it asked for. A handoff alone doesn't end the session, so the
  handoff skill doesn't count. If no pass comes within 40000 tokens of that call, the re-arm
  resumes, looking only past that point.

On (decide()): soft speaks on Stop only, as a block. Wrap-up and hard speak on Stop as a block
and on PostToolUse as additionalContext; one that spoke on PostToolUse doesn't repeat at the Stop.
Off: only the hard tier, once per crossing (no +20k re-arm), as a user-only systemMessage, on
whichever event comes first.

Background work, two rules:
- busy: a task of stop_ring.WAITS (a subagent, shell, workflow or cloud session: work whose
  result the turn waits on; a Monitor is relabeled by stop_ring.task_types). Soft and wrap-up
  stay quiet and stay armed; hard says its busy variant (pass compact: a compact keeps the tasks
  alive).
- blocked: any task a plain pass would be refused for (lanelib.plain_pass_blockers, the rule
  pass-respawn uses: everything but `dream` and an `artifact watch`, monitors and teammates
  too; without lanelib, every task). Every tier then says to pass in compact mode.
Busy or blocked, the text ends by naming each such task with its id (TASKS_NOTE): the session
stops the finished ones before the handoff and passes plain if none is left (pass skill step 2).
On Stop the payload's background_tasks decide. PostToolUse has no task list, so the session's
stop record (stops/<session>.json, which stop-ring.sh writes at every Stop) decides when it was
written within the last 10 minutes: its `waits` for busy, its `tasks` for blocked. With no such
record, or one whose task list or waits can't be read (a wait stop_ring.WAITS doesn't name
included), the state is unknown: every tier says compact mode, which is safe either way, and its
text says so without claiming tasks run. A task started since the
last Stop isn't seen.

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
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import autopass_state as aps  # noqa: E402
import stop_ring  # noqa: E402

TAIL, WIDE = 512 * 1024, 8 * 1024 * 1024
REARM = 20000             # the hard tier's re-arm step, at most
HYSTERESIS = 50000        # how far under a tier the count must fall to re-arm it, at most
HANDOFF_GRACE = 40000     # a pass call older than this many tokens no longer holds the re-arm
STOP_FRESH = 600
STOP_WAIT, STOP_POLL = 1.5, 0.025  # at a Stop, how long to wait for the final reply, and how often
MODE_TTL = 60
PASS_SKILL = "pass"
# A typed /pass (or /pass compact) is a main-chain user entry whose text carries the command:
# "<command-name>/pass</command-name>" beside <command-message> and <command-args> (the shape
# Claude Code writes for every slash command; seen for /clear and /compact).
# Anchored at the <command-message> block a real command starts with, so a message that only
# quotes the marker doesn't count.
TYPED_PASS = re.compile(r"\A\s*<command-message>[^<]*</command-message>\s*"
                        r"<command-name>\s*/pass\s*</command-name>")


LEAD = "[autopass] Context is at {n}, auto-compact near {c}"
COMPACT_WHY = "(a compact keeps background tasks alive; a plain pass would be refused)"
UNKNOWN_WHY = "(it's safe whether or not background work is running)"
# Added to a text when tasks would block a plain pass, naming each with its id (the first
# NUDGE_SHOWN, descriptions cut to NUDGE_CHARS): to the model, so it stops the finished ones
# before the handoff (pass skill step 2), or, off, to Hayden.
NUDGE_SHOWN, NUDGE_CHARS = 10, 80
TASKS_NOTE = (" Running: {tasks}. Before the handoff, TaskStop each one whose job is done, ask "
              "Hayden about any you can't tie to finished work, and pass plain if none is left "
              "(pass skill step 2).")
TASKS_SEEN = " Running: {tasks}."
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
    "wrap_unknown": LEAD + ". Finish the step you are on and don't start another. If more than "
                           "this step is left, run the pass skill in compact mode now "
                           + UNKNOWN_WHY + ".",
    "hard_unknown": LEAD + ": hand off now. Run the pass skill in compact mode " + UNKNOWN_WHY
                         + ".",
    "off_unknown": "Context {n}, auto-compact near {c}: hand off now (/pass compact is safe if "
                   "background work may be running).",
    "off": "Context {n}, auto-compact near {c}: hand off now (/pass).",
    "off_compact": "Context {n}, auto-compact near {c}: hand off now (/pass compact: background "
                   "tasks are running).",
}


def main_chain(line: bytes):
    """A main-chain user or assistant transcript line as a dict, or None."""
    if b'"assistant"' not in line and b'"user"' not in line:
        return None
    try:
        d = json.loads(line)
    except (ValueError, RecursionError):   # json recurses on nesting
        return None
    if not isinstance(d, dict) or d.get("isSidechain") or d.get("type") not in ("user",
                                                                                "assistant"):
        return None
    return d


def compact_boundary(line: bytes) -> bool:
    """Whether a transcript line is a main-chain compact boundary (Claude Code's system entry
    with subtype compact_boundary): no usage before it is the context now."""
    if b'"compact_boundary"' not in line:
        return False
    try:
        d = json.loads(line)
    except (ValueError, RecursionError):   # json recurses on nesting
        return False
    return isinstance(d, dict) and not d.get("isSidechain") and d.get("type") == "system" \
        and d.get("subtype") == "compact_boundary"


def usage_total(d: dict):
    """The context size a main-chain entry records (an assistant's), or None."""
    msg = d.get("message")
    u = msg.get("usage") if d.get("type") == "assistant" and isinstance(msg, dict) else None
    if not isinstance(u, dict):
        return None
    parts = [u.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens",
                                   "cache_creation_input_tokens")]
    if not all(aps.is_int(p) and p >= 0 for p in parts) or not sum(parts):
        return None
    return sum(parts)


def scan(path):
    """(the last main-chain assistant usage or None, whether the last main-chain user or
    assistant entry is an assistant's: the turn's final reply is on disk). It is False too
    when no such entry is in reach (an empty file, or one final user line past WIDE), since
    the reply that lands is then readable; it is None when the transcript can't be read: no
    reply will land there to wait for. A compact boundary met first ends the walk with no
    usage: the first reply after a compact can reach the transcript after the tool call's
    hook, and the usage before the boundary is the pre-compact context."""
    final = None
    if not isinstance(path, str) or not path:
        return None, None
    try:
        with open(path, "rb") as f:
            size = f.seek(0, os.SEEK_END)
            for span in (TAIL, WIDE):
                f.seek(max(0, size - span))
                lines = f.read(span).split(b"\n")
                if size > span:
                    lines = lines[1:]  # the first line is cut
                for line in reversed(lines):
                    if compact_boundary(line):
                        return None, final is True
                    d = main_chain(line)
                    if d is None:
                        continue
                    if final is None:
                        final = d["type"] == "assistant"
                    n = usage_total(d)
                    if n is not None:
                        return n, final
                if size <= span:
                    break
    except OSError:
        return None, None
    return None, final is True


def tokens(path) -> int | None:
    """The last main-chain assistant usage in the transcript at path, or None."""
    return scan(path)[0]


def stop_tokens(path, sid):
    """The count at a Stop. The turn's final reply reaches the transcript about 100 ms into
    the Stop hook (spike A8), so wait up to STOP_WAIT for it; past that, log a line and use
    the last count on disk (the previous turn's). An unreadable transcript doesn't wait."""
    n, final = scan(path)
    deadline = time.monotonic() + STOP_WAIT
    while final is False and time.monotonic() < deadline:
        time.sleep(STOP_POLL)
        n, final = scan(path)
    if final is False:
        sys.stderr.write("%s context-watch %s: no final reply in the transcript after %.1f s; "
                         "%s\n" % (time.strftime("%F %T"), sid, STOP_WAIT,
                                   "no count" if n is None else "used the previous reply's"))
    return n


def runs_pass_respawn(command: str) -> bool:
    """Whether a Bash command starts with pass-respawn (after blanks and an optional `!`), as
    the pass skill runs it: not one that only names it (`grep pass-respawn README.md`)."""
    c = command.lstrip()
    if c.startswith("!"):
        c = c[1:].lstrip()
    word = c.split(None, 1)[0] if c.split() else ""
    return word == "pass-respawn" or word.endswith("/pass-respawn")


def typed_pass(content) -> bool:
    """Whether a user entry's content (a string, or a list of text blocks) is a typed /pass."""
    texts = [content] if isinstance(content, str) else [
        c.get("text") for c in content if isinstance(c, dict) and c.get("type") == "text"
    ] if isinstance(content, list) else []
    return any(isinstance(t, str) and TYPED_PASS.match(t) for t in texts)


def starts_handoff(line: bytes) -> bool:
    """Whether a transcript line starts a pass: a main-chain assistant tool call (the pass
    skill, pass-respawn), or a main-chain user entry that is a typed /pass. A typed "handoff
    and pass" reaches the model as text and makes it call the pass skill, which counts."""
    typed = b"<command-name>" in line and b"/pass" in line
    if not typed and (b'"tool_use"' not in line
                      or not (b'"Skill"' in line or b"pass-respawn" in line)):
        return False
    try:
        d = json.loads(line)
    except (ValueError, RecursionError):   # json recurses on nesting
        return False
    if not isinstance(d, dict) or d.get("isSidechain"):
        return False
    msg = d.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if d.get("type") == "user":
        return typed and typed_pass(content)
    if d.get("type") != "assistant":
        return False
    for c in content if isinstance(content, list) else []:
        if not isinstance(c, dict) or c.get("type") != "tool_use":
            continue
        args = c.get("input") if isinstance(c.get("input"), dict) else {}
        if c.get("name") == "Skill" and args.get("skill") == PASS_SKILL:
            return True
        if c.get("name") == "Bash" and isinstance(args.get("command"), str) \
                and runs_pass_respawn(args["command"]):
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
           "handing_off": rec.get("handing_off") is True,
           "handoff_at": num(rec.get("handoff_at"))}
    if isinstance(rec.get("mode"), dict):
        out["mode"] = rec["mode"]
    return out


def hysteresis(tiers: dict, tier: str) -> int:
    return min(HYSTERESIS, tiers[tier] // 4)


def rearm_step(tiers: dict) -> int:
    """The hard tier's re-arm step: 20k, or half the room left before auto-compact."""
    return min(REARM, max(1, (tiers["compact_at"] - tiers["hard"]) // 2))


def rearm(rec: dict, n: int, tiers: dict) -> None:
    """A count more than hysteresis() under a tier re-arms it."""
    for t in aps.TIER_NAMES:
        if n < tiers[t] - hysteresis(tiers, t):
            rec["fired"][t] = None
    if n < tiers["hard"] - hysteresis(tiers, "hard"):
        rec["off_hard"] = None
        rec.update(hard_time=None, hard_offset=None, handing_off=False, handoff_at=None)


def top_tier(n: int, tiers: dict):
    for t in reversed(aps.TIER_NAMES):
        if n >= tiers[t]:
            return t
    return None


def armed(rec: dict, tier: str, n: int, tiers: dict, handoff, size=None) -> bool:
    """Whether tier may fire at n. handoff(offset) -> whether a pass started past it; asked
    only for the hard tier's re-arm, and remembered (handing_off) until the count is
    HANDOFF_GRACE past where it was seen. Then the scan starts again from size, the
    transcript's size now."""
    last = rec["fired"][tier]
    if last is None:
        return True
    if tier != "hard" or n < last + rearm_step(tiers):
        return False
    if rec["handing_off"]:
        if rec["handoff_at"] is not None and n < rec["handoff_at"] + HANDOFF_GRACE:
            return False
        rec.update(handing_off=False, handoff_at=None,
                   hard_offset=size if aps.is_int(size) else None)
        return True
    if handoff(rec["hard_offset"]):
        rec.update(handing_off=True, handoff_at=n)
        return False
    return True


def due(rec: dict, n: int, tiers: dict, event: str, handoff, size=None):
    """(top tier, whether it is due with autopass on, whether the off line is due), after the
    re-arm, which changes rec in place."""
    rearm(rec, n, tiers)
    top = top_tier(n, tiers)
    on_due = top is not None and (event == "Stop" or top != "soft") \
        and armed(rec, top, n, tiers, handoff, size)
    off_due = n >= tiers["hard"] and rec["off_hard"] is None
    return top, on_due, off_due


def step(rec: dict, n: int, tiers: dict, event: str, mode, work, handoff=lambda o: False,
         size=None, now=None):
    """What this event says: (text key or None, "block" | "context" | "system" | None), with
    rec updated in place. mode() -> on (True or False, or None: say nothing and mark nothing),
    work() -> "busy" | "blocked" | "unknown" | None, both run only when something would fire.
    size is the transcript's size now, kept with a hard firing for the handoff check."""
    top, on_due, off_due = due(rec, n, tiers, event, handoff, size)
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
            # "unknown" comes only from a tool call's stop-record lookup, and soft never fires
            # on a tool call, so there is no soft_unknown text.
            key = top + {"blocked": "_compact", "unknown": "_unknown"}.get(state, "")
            for t in aps.TIER_NAMES:
                if n >= tiers[t]:
                    rec["fired"][t] = n
        if top == "hard":
            rec.update(hard_time=float(now if now is not None else time.time()),
                       hard_offset=size if aps.is_int(size) else None, handing_off=False,
                       handoff_at=None)
        return key, ("block" if event == "Stop" else "context")
    if not off_due:
        return None, None
    rec["off_hard"] = n
    state = work()
    return {"busy": "off_compact", "blocked": "off_compact",
            "unknown": "off_unknown"}.get(state, "off"), "system"


def entries(tasks, path=None) -> list:
    """background_tasks as stop-ring.sh records them (stop_ring.task_entries): each one's label
    (a Monitor as `monitor`, from the transcript at path; the Artifact tool's watch as
    `artifact watch`; `unlabeled` for none), id and description."""
    raw = tasks if isinstance(tasks, list) else []
    return stop_ring.task_entries(raw, stop_ring.task_types(raw, path))


def work_state(waits: list, tasks: list):
    """(busy, blocked or None; the tasks that block a plain pass, which the nudge names).
    Without lanelib the rule can't be applied (pass-respawn can't run either), so every task
    blocks: compact mode is safe either way."""
    lib = aps.lanelib()
    if lib:
        blockers = lib.plain_pass_blockers(tasks)
    else:
        blockers = [{"label": k if isinstance(k, str) and k else "unlabeled"}
                    for k in (t.get("label") if isinstance(t, dict) else t for t in tasks)]
    if any(w in stop_ring.WAITS for w in waits if isinstance(w, str)):
        return "busy", blockers
    return ("blocked" if blockers else None), blockers


def stop_work(d: dict):
    tasks = entries(d.get("background_tasks"), d.get("transcript_path"))
    return work_state([t["label"] for t in tasks], tasks)


def recorded_work(sid: str):
    """work_state from the stop record when it is under STOP_FRESH seconds old and lists its
    tasks and waits, every wait one stop_ring.WAITS names; else ("unknown", []) (the texts then
    say compact mode is safe either way), as pass-respawn refuses a record it can't read."""
    rec = aps.load_json(os.path.join(aps.state_dir(), "stops", sid + ".json"))
    when = rec.get("time") if isinstance(rec, dict) else None
    try:
        fresh = isinstance(when, (int, float)) and 0 <= time.time() - when < STOP_FRESH
    except OverflowError:   # json reads ints past a float's range
        fresh = False
    if not fresh:
        return "unknown", []
    tasks, waits = rec.get("tasks"), rec.get("waits")
    if not (isinstance(tasks, list) and isinstance(waits, list)) or \
            any(not isinstance(w, str) or w not in stop_ring.WAITS for w in waits):
        return "unknown", []
    return work_state(waits, tasks)


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
    """(on, a fresh cache entry to store, or None when the cached one served). An entry holds
    for MODE_TTL seconds, and only while the tab flag's generation is the one read before its
    decide(): a toggle in between changes it, so a stale store never serves."""
    m = rec.get("mode")
    now = time.time()
    gen = aps.flag_generation(pane)
    if (isinstance(m, dict) and isinstance(m.get("on"), bool) and m.get("flag") == gen
            and isinstance(m.get("at"), (int, float)) and 0 <= now - m["at"] < MODE_TTL):
        return m["on"], None
    on, source = aps.decide(cwd, pane)
    return on, {"on": on, "source": source, "at": now, "flag": gen}


def named(tasks: list) -> str:
    """The tasks for the nudge: the first NUDGE_SHOWN as lanelib.describe_task names them, with
    every id, then "+N more"."""
    lib = aps.lanelib()
    shown = [lib.describe_task(t, NUDGE_CHARS) if lib else t["label"]
             for t in tasks[:NUDGE_SHOWN]]
    more = len(tasks) - NUDGE_SHOWN
    return ", ".join(shown) + (f", +{more} more" if more > 0 else "")


def render(key: str, kind: str, n: int, tiers: dict, tasks=()) -> dict:
    text = TEXTS[key].format(n=aps.kilo(n), c=aps.kilo(tiers["compact_at"]))
    if tasks:
        text += (TASKS_SEEN if kind == "system" else TASKS_NOTE).format(tasks=named(tasks))
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
    if event not in ("Stop", "PostToolUse", "SessionStart") or not isinstance(sid, str) \
            or not stop_ring.SID.fullmatch(sid):
        return None
    if event == "SessionStart":
        if d.get("source") == "compact":
            aps.merge_ctx(sid, {"tokens": None, "time": time.time()})
        return None
    path = d.get("transcript_path")
    n = stop_tokens(path, sid) if event == "Stop" else tokens(path)
    if n is None:
        return None
    now = time.time()
    ctx = aps.write_ctx(sid, n, now)
    stop_ring.prune(os.path.dirname(aps.ctx_path(sid)), now)
    if os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "0":
        return None
    # `window` may be stale (the model changed): part 2b's widget rewrites it on every render.
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

    blockers = []

    def work():
        state, blockers[:] = stop_work(d) if event == "Stop" else recorded_work(sid)
        return state

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
    return render(key, kind, n, tiers, blockers) if key else None


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
