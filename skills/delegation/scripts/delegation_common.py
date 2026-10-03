"""Shared pieces for the delegation scripts (stdlib only): the ledger, the liveness index, the
policy path and the [deadline] helpers.

The ledger is an append-only JSONL file of pointers, never content: ids, types, paths,
exit codes, and whether a report validated. Briefs and outputs stay in the transcripts
and rollouts they already live in.

Beside it, agents/<id>.json is the per-agent liveness index: the latest state of each Claude
agent, rewritten at its starts and stops (and once per activation by the deadline nudge), so a
reader gets one agent's state without folding the whole ledger.

watches/<id>.json is a long wait that `delegation-ledger wait` or a codex-delegate wrapper
records and the watch guard (a Stop hook) reads; the comment above WATCH_STATES documents its
fields, and Waiter makes a waiter's changes.
"""
import contextlib
import copy
import datetime
import fcntl
import glob
import json
import math
import os
import re
import secrets
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
SCHEMA_PATH = os.path.join(os.path.dirname(HERE), "report.schema.json")


def policy_path():
    """policy.toml, or $DELEGATION_POLICY (the live harness and the tests point it elsewhere)."""
    return os.environ.get("DELEGATION_POLICY") or os.path.join(os.path.dirname(HERE),
                                                               "policy.toml")


def norm_id(agent_id):
    """An agent id as the ledger and the index key it: without Claude Code's `agent-` prefix."""
    s = str(agent_id or "")
    return s[len("agent-"):] if s.startswith("agent-") else s


def is_positive(v):
    """A positive, finite int or float. TOML allows inf and nan, and a bool is not a number."""
    return (not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)
            and v > 0)


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)


def state_dir(home=None):
    base = (os.environ.get("XDG_STATE_HOME")
            or os.path.join(home or os.path.expanduser("~"), ".local", "state"))
    return os.path.join(base, "dotclaude")


def ledger_path():
    return os.environ.get("DELEGATION_LEDGER") or os.path.join(state_dir(), "delegations.jsonl")


def append_row(row):
    path = ledger_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    line = json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n"
    with open(path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(line)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def agents_dir():
    return os.path.join(state_dir(), "agents")


def watches_dir():
    return os.path.join(state_dir(), "watches")


def _id_path(directory, xid, what):
    """<directory>/<xid>.json, for an id that is a plain basename (not empty, no dot first)."""
    xid = str(xid)
    if not xid or xid.startswith(".") or os.path.basename(xid) != xid:
        raise ValueError(f"not {what}: {xid!r}")
    return os.path.join(directory, f"{xid}.json")


def _agent_path(aid):
    return _id_path(agents_dir(), aid, "an agent id")


class LockBusy(Exception):
    """A bounded file_lock wait ran out before the lock came free."""


@contextlib.contextmanager
def file_lock(path, until=None, clock=time.monotonic):
    """An exclusive flock on path. With `until` (a clock() deadline) it never blocks: it
    retries until then and raises LockBusy if the lock didn't come free."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX if until is None
                            else fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if clock() >= until:
                    raise LockBusy(path) from None
                time.sleep(0.01)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def dir_lock(directory, until=None, clock=time.monotonic):
    """file_lock on <directory>/.lock, which read-modify-writes there hold."""
    return file_lock(os.path.join(directory, ".lock"), until, clock)


def write_json(path, obj):
    """Write obj to a temp file beside path, then os.replace it in, so a reader never sees a
    torn file."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=f".{os.path.basename(path)}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_agent_state(aid):
    """The agent's index entry, or {} when it is missing or malformed."""
    try:
        with open(_agent_path(aid)) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def update_agent_state(aid, fn):
    """Read-modify-write the agent's index entry under agents/.lock. fn gets the current dict
    and changes it in place or returns a new one. The result goes to a temp file that is then
    os.replace'd, so a reader never sees a torn file."""
    path = _agent_path(aid)
    with dir_lock(agents_dir()):
        cur = read_agent_state(aid)
        new = fn(cur)
        new = cur if new is None else new
        write_json(path, new)
    return new


def prune_agent_states(days=7):
    """Remove index files (and temp files a crash left) whose mtime is over `days` old. They
    are program-owned: only the ledger hook writes an agent's file, at its starts and stops
    and at its deadline nudge."""
    cutoff = time.time() - days * 86400
    with dir_lock(agents_dir()):
        for p in (glob.glob(os.path.join(agents_dir(), "*.json"))
                  + glob.glob(os.path.join(agents_dir(), ".*.tmp"))):
            with contextlib.suppress(OSError):
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)


def activation_age(entry, now):
    """Seconds the agent's current activation has run, from its index entry's
    activation_start; None when the entry is empty (the file is missing or unparsable) or its
    start doesn't parse. Both deadline hooks fail open on None."""
    try:
        return now - parse_iso(entry["activation_start"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return None


DEADLINE_KEYS = {"nudge_min", "stop_min"}
# The report path a stopped agent needs: the handback, SendMessage (a teammate's report), and
# ToolSearch to load SendMessage, which is deferred for a teammate. `allow` may add to it.
REPORT_PATH = ("SubagentHandback", "SendMessage", "ToolSearch")


def check_deadline(table):
    """Raise ValueError unless policy.toml's [deadline] has the shape both deadline hooks rely
    on: `allow` a list of tool names that keeps the whole REPORT_PATH, a `default` budget, and
    every budget { nudge_min = N } with an optional stop_min past it, in positive minutes. An
    allow list without the report path would leave a stopped agent no way to report, so it is
    malformed, and a malformed policy keeps the report path open."""
    if not isinstance(table, dict):
        raise ValueError("policy.toml: missing table [deadline]")
    allow = table.get("allow")
    if not isinstance(allow, list) or not all(isinstance(t, str) for t in allow):
        raise ValueError("policy.toml: [deadline] allow must be a list of tool names")
    missing = [t for t in REPORT_PATH if t not in allow]
    if missing:
        raise ValueError("policy.toml: [deadline] allow lacks the report path: "
                         + ", ".join(missing))
    if "default" not in table:
        raise ValueError("policy.toml: [deadline] lacks a default budget")
    for role, b in table.items():
        if role == "allow":
            continue
        if (not isinstance(b, dict) or set(b) - DEADLINE_KEYS
                or not is_positive(b.get("nudge_min"))
                or ("stop_min" in b and not is_positive(b["stop_min"]))):
            raise ValueError(f"policy.toml: [deadline] {role} must be {{ nudge_min = N }} with "
                             "an optional stop_min, in positive minutes")
        if b.get("stop_min", 2 * b["nudge_min"]) <= b["nudge_min"]:
            raise ValueError(f"policy.toml: [deadline] {role}: stop_min must be past nudge_min")


def deadline_for(policy, role):
    """(nudge_s, stop_s) for a role: its own [deadline] budget, else `default`. stop_min
    defaults to twice nudge_min."""
    table = policy["deadline"]
    b = table[role] if role in table and role != "allow" else table["default"]
    return b["nudge_min"] * 60, b.get("stop_min", 2 * b["nudge_min"]) * 60


def minutes_text(seconds):
    """Minutes as a deadline message prints them: 61.2, 0.4, 125."""
    return f"{round(seconds / 60, 1):g}"


def tool_list(names):
    """[deadline] allow as a deadline message prints it: "A", "A and B", "A, B and C"."""
    names = list(names)
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def read_rows(tail=None):
    """The ledger's rows. With `tail` (bytes), only the end of the file is read, and the line
    the cut split is dropped."""
    try:
        with open(ledger_path(), "rb") as f:
            cut = False
            if tail is not None:
                f.seek(0, os.SEEK_END)
                cut = f.tell() > tail
                # From one byte before the cut, the first line is always the split one: it is
                # empty when the cut falls on a line end, so dropping it never loses a row.
                f.seek(max(0, f.tell() - tail - 1))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except FileNotFoundError:
        return []
    rows = []
    for line in lines[1:] if cut else lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # a torn write after a crash; skip it rather than fail the reader
    return rows


def first_row_ts(limit=100):
    """The ts of the ledger's first row that has a valid one, or None. It reads at most `limit`
    lines, so a session start can afford it, and a damaged head can neither silence the monthly
    nudge nor fire it early."""
    try:
        with open(ledger_path(), "rb") as f:
            for _, line in zip(range(limit), f):
                try:
                    ts = json.loads(line).get("ts")
                    parse_iso(ts)
                    return ts
                except (ValueError, AttributeError, TypeError):
                    continue
    except OSError:
        pass
    return None


NOT_LIFECYCLE = ("policy", "nudge", "exclude")
MONTH_DAYS = 30  # the monthly audit's window, and how often `due` asks for it


def fold(rows):
    """Latest row per (runner, id), plus the first-seen timestamp. SubagentStart fires on
    every teammate message, so an id can have many start/stop pairs; the latest wins.
    subagent-policy's `policy` rows, the deadline's `nudge` rows and `exclude` rows are skipped
    here (tail shows them, audit counts the denials, and the monthly audit reads the
    exclusions). A stop row with no `status` (an older codex-delegate's finish or crash row)
    clears the status and the error a cancelled turn before it left: it ended its own turn,
    which finished or crashed."""
    out = {}
    for r in rows:
        key = (r.get("runner"), r.get("id"))
        if key[1] is None or r.get("event") in NOT_LIFECYCLE:
            continue  # a denial or a nudge, not a lifecycle event
        first = out.get(key, {}).get("first_ts", r.get("ts"))
        merged = dict(out.get(key, {}))
        merged.update(r)  # None overrides too: a clean resume must clear an old error
        if r.get("event") == "stop" and "status" not in r:
            merged.pop("status", None)
            if "error" not in r:
                merged.pop("error", None)
        merged["first_ts"] = first
        merged["event"] = r.get("event")
        out[key] = merged
    return out


def load_schema():
    with open(SCHEMA_PATH) as f:
        return json.load(f)


def validate_report(obj, schema=None):
    """Errors against report.schema.json; [] means valid. Covers exactly the keywords the
    schema uses (object/required/additionalProperties/enum/string/array of strings), so a
    schema change that adds a keyword must extend this too (test_ledger checks the pair)."""
    schema = schema or load_schema()
    if not isinstance(obj, dict):
        return ["report is not a JSON object"]
    errs = []
    props = schema["properties"]
    for k in schema["required"]:
        if k not in obj:
            errs.append(f"missing field: {k}")
    if schema.get("additionalProperties") is False:
        errs += [f"unexpected field: {k}" for k in obj if k not in props]
    for k, spec in props.items():
        if k not in obj:
            continue
        v = obj[k]
        if spec["type"] == "string":
            if not isinstance(v, str):
                errs.append(f"{k}: not a string")
            elif "enum" in spec and v not in spec["enum"]:
                errs.append(f"{k}: {v!r} not in {spec['enum']}")
        elif spec["type"] == "array":
            if not isinstance(v, list) or not all(isinstance(i, str) for i in v):
                errs.append(f"{k}: not an array of strings")
    return errs


FENCE_RE = re.compile(r"```[ \t]*(?:json)?[ \t]*\n\s*(\{.*?\})\s*\n[ \t]*```", re.S | re.I)


def extract_report(text):
    """The report a Claude agent ends with: its last fenced JSON block, else the whole
    message as JSON. Returns (obj, None) or (None, reason)."""
    if not text or not text.strip():
        return None, "empty final message"
    blocks = FENCE_RE.findall(text)
    candidates = [blocks[-1]] if blocks else [text.strip()]
    for c in candidates:
        try:
            return json.loads(c), None
        except ValueError:
            pass
    return None, "no parseable JSON report"


def report_check(text):
    """(report_ok, status, first_error) for a final message."""
    obj, why = extract_report(text)
    if obj is None:
        return False, None, why
    errs = validate_report(obj)
    status = obj.get("status") if isinstance(obj, dict) else None
    return (not errs), status, (errs[0] if errs else None)


def agent_meta(data):
    """The agent's meta.json, which sits beside its transcript under the parent session's
    subagents/ directory, or {} when there is none."""
    tp, aid = data.get("transcript_path") or "", norm_id(data.get("agent_id"))
    if not tp or not aid:
        return {}
    base = tp[:-len(".jsonl")] if tp.endswith(".jsonl") else tp
    try:
        with open(os.path.join(base, "subagents", f"agent-{aid}.meta.json")) as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def agent_role(data, meta=None):
    """The role an agent was spawned as. For an agent-team teammate, the hook input's
    agent_type is the teammate's name and the role is meta.json's customAgentType
    (observed on Claude Code 2.1.286), so role rules keyed on agent_type alone would miss it."""
    meta = agent_meta(data) if meta is None else meta
    return meta.get("customAgentType") or data.get("agent_type") or ""


def _stat_fields(pid):
    """The fields of /proc/<pid>/stat from field 3 (state) on, or None. They are split after
    the last ") ", since the command name may hold spaces."""
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            return f.read().rsplit(") ", 1)[1].split()
    except (OSError, TypeError, ValueError, IndexError):
        return None


def proc_ppid(pid):
    """The parent pid of pid (stat field 4), or None."""
    fields = _stat_fields(pid)
    try:
        return int(fields[1])
    except (TypeError, ValueError, IndexError):
        return None


def _start_of(fields):
    """Field 22 (starttime, in clock ticks since boot) from _stat_fields' list, or None."""
    try:
        return int(fields[19])
    except (TypeError, ValueError, IndexError):
        return None


def proc_start(pid):
    """Field 22 of /proc/<pid>/stat (starttime, in clock ticks since boot), or None."""
    return _start_of(_stat_fields(pid))


def pid_alive(pid, start=None):
    """Whether pid is running. A zombie (state Z) or a dead task (X) has exited and only waits
    to be reaped, so it is gone; a pid whose stat can't be read but whose /proc entry exists
    counts as running. Given `start` (a session file's procStart), the process must also have
    that start time, so a pid the kernel reused for another process reads as gone. No `start`
    means don't check it."""
    try:
        if pid is None or not os.path.exists(f"/proc/{int(pid)}"):
            return False
    except (TypeError, ValueError):
        return False
    fields = _stat_fields(pid)
    if fields and fields[0] in ("Z", "X"):
        return False
    return start is None or str(_start_of(fields)) == str(start)


SESSION_WALK = 6  # how many parents up claude_ancestor looks for a sessions file


def ancestors():
    """This process's pid, then its parent's and so on up, short of pid 1, nearest first."""
    out, pid = [], os.getpid()
    while pid is not None and pid > 1 and pid not in out and len(out) < 64:
        out.append(pid)
        pid = proc_ppid(pid)
    return out


def claude_ancestor(chain=None):
    """(pid, procStart, sessionId) of the nearest process in `chain` (ancestors(), this process
    first), at most SESSION_WALK parents up, whose ~/.claude/sessions/<pid>.json names that pid
    and its procStart: the Claude Code process this one runs under, and its session as that
    file names it (None when it names none). None when there is no such process (outside Claude
    Code, or sandboxed, where no pid outside the sandbox can be seen). A `claude -p` run writes
    its own sessions file, so a nested one finds itself, not its parent."""
    for pid in (ancestors() if chain is None else chain)[:SESSION_WALK + 1]:
        try:
            with open(os.path.expanduser(f"~/.claude/sessions/{pid}.json")) as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        start = proc_start(pid)
        if (isinstance(d, dict) and d.get("pid") == pid
                and (d.get("procStart") is None or str(d["procStart"]) == str(start))):
            sid = d.get("sessionId")
            return pid, start, (sid if isinstance(sid, str) and sid else None)
    return None


def pids_visible():
    """False inside the sandbox, whose PID namespace (each sandboxed command gets its own) hides
    every pid outside it, so no pid check means anything there. SANDBOX_RUNTIME=1, set only
    inside, says so. So does a CLAUDE_PID that can't be seen, unless claude_ancestor finds a live
    Claude process anyway: then CLAUDE_PID is only stale, inherited from a process that has
    ended (a tmux server started from a Claude Bash call, say). True when CLAUDE_PID is unset
    (tmux, a plain terminal)."""
    if os.environ.get("SANDBOX_RUNTIME") == "1":
        return False
    pid = os.environ.get("CLAUDE_PID")
    return not pid or pid_alive(pid) or claude_ancestor() is not None


def codex_state(e, visible=True):
    """(verdict, evidence) for a folded codex ledger entry, shared by `delegation-ledger
    open` and `watch` and by `codex-delegate status`. Codex runs under a detached supervisor
    and writes its events straight to the file, so it outlives a wrapper that was killed
    (Claude's Bash tool stops a command at its time limit, with its whole process tree); a run
    with no stop row is therefore not necessarily dead. With `visible`
    False (see pids_visible), the pid checks mean nothing, so it says that instead."""
    event = e.get("event")
    out = e.get("out") or ""
    events = os.path.join(out, "events.jsonl")
    age = ((time.time() - os.path.getmtime(events)) / 60) if os.path.exists(events) else None
    codex_pid = codex_proc(e)[0]
    codex_alive = codex_running(e)
    wrapper_alive = codex_wrapper_alive(e)
    has_report = os.path.exists(os.path.join(out, "report.json"))
    run = e.get("run_id")
    if event == "stop":
        verdict = "cancelled" if e.get("status") == "cancelled" else "finished"
    elif not visible:
        verdict = "pid not visible in the sandbox"
    elif codex_alive and wrapper_alive:
        verdict = "running"
    elif codex_alive:
        w = codex_watch(run)
        verdict = ("running (its wrapper is gone; " + (
            f"`delegation-ledger wait --resume {w['id']}` waits and finalizes)" if w else
            f"`codex-delegate finalize {run}` once it ends)"))
    elif event == "pending" and wrapper_alive:
        verdict = "starting"
    elif codex_unstarted(e) and e.get("thread_id"):  # a resume's wrapper died before Codex
        verdict = f"never restarted its thread: `codex-delegate resume {run}`"
    elif codex_unstarted(e):
        verdict = "never started a thread: rerun it with `codex-delegate run`"
    elif has_report:
        verdict = f"ended without a stop row: `codex-delegate finalize {run}`"
    else:
        verdict = f"died: `codex-delegate resume {run}`"
    pids = (f"codex pid {codex_pid} {'alive' if codex_alive else 'gone'}, "
            f"wrapper {'alive' if wrapper_alive else 'gone'}" if visible else
            f"codex pid {codex_pid} and its wrapper not visible in the sandbox")
    evidence = (f"{pids}, "
                + (f"last event {age:.0f} min ago" if age is not None else "no events file")
                + (", report.json present" if has_report else ""))
    return verdict, evidence


def codex_wrapper_alive(e):
    """Whether a folded codex entry's latest wrapper runs: its wrapper_pid, with the
    wrapper_start its pending row recorded (older rows have none, so only the pid counts)."""
    return pid_alive(e.get("wrapper_pid"), e.get("wrapper_start"))


def codex_pid_path(out):
    return os.path.join(out or "", "codex.pid")


def codex_rc_path(out):
    return os.path.join(out or "", "codex.rc")


def _codex_turn_file(path, e):
    """The JSON object at path when the entry's latest wrapper wrote it (its wrapper_pid and,
    when the entry has one, wrapper_start match), else None: <out> holds every turn's files,
    and a resume's wrapper is a new one."""
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if (isinstance(d, dict) and d.get("wrapper_pid") is not None
            and d.get("wrapper_pid") == e.get("wrapper_pid")
            and (e.get("wrapper_start") is None
                 or str(d.get("wrapper_start")) == str(e.get("wrapper_start")))):
        return d
    return None


def codex_proc(e):
    """(pid, procStart) of the Codex process of a folded codex entry's current turn, procStart
    None when unknown; (None, None) when none is known to have started. The detached supervisor
    writes <out>/codex.pid right after its Popen, before the ledger hears of Codex (a wrapper
    SIGKILLed before thread.started writes no row with the pid), so that file counts when it
    names the entry's latest wrapper. Else a row past pending names the pid: a pending row
    carries none, and a folded one's is the previous turn's."""
    d = _codex_turn_file(codex_pid_path(e.get("out")), e)
    if d is not None:
        return d.get("pid"), d.get("start")
    return (None, None) if e.get("event") == "pending" else (e.get("pid"), None)


def codex_supervisor(e):
    """(pid, procStart) of the detached process that runs the entry's current turn's Codex and
    writes codex.rc when it ends, from codex.pid; (None, None) when unknown."""
    d = _codex_turn_file(codex_pid_path(e.get("out")), e) or {}
    return d.get("supervisor_pid"), d.get("supervisor_start")


def codex_rc(e):
    """{"rc", "ended"} for the entry's current turn, which its supervisor writes to
    <out>/codex.rc once Codex ends; None while Codex runs, or when the supervisor was killed
    first and Codex's exit code is unknown."""
    return _codex_turn_file(codex_rc_path(e.get("out")), e)


def codex_running(e):
    """Whether the entry's current turn still runs: its Codex process (codex_proc), or the
    supervisor that is about to record Codex's exit code (codex_supervisor)."""
    return pid_alive(*codex_proc(e)) or pid_alive(*codex_supervisor(e))


def codex_live(e):
    """Whether a folded codex entry's run is still going: its Codex runs, or a pending row's
    wrapper does (Codex hasn't started yet)."""
    return codex_running(e) or (e.get("event") == "pending" and codex_wrapper_alive(e))


def events_thread_id(out):
    """The thread id in <out>/events.jsonl's thread.started, or None. A wrapper that left
    before Codex started its thread (at --max-wait, or killed) never recorded it."""
    try:
        with open(os.path.join(out or "", "events.jsonl")) as f:
            for line in f:
                if '"thread.started"' not in line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") == "thread.started" and e.get("thread_id"):
                    return e["thread_id"]
    except OSError:
        pass
    return None


def codex_unstarted(e):
    """Whether a codex run's latest row is a pending one whose wrapper died before it launched
    Codex: nothing runs, and there is nothing to finalize. That means no codex.pid from this
    wrapper, and for a first turn no thread.started in events.jsonl (a resume's file holds the
    earlier turns', so only the pid file tells there)."""
    return (e.get("event") == "pending" and not codex_live(e) and codex_proc(e)[0] is None
            and (bool(e.get("thread_id")) or events_thread_id(e.get("out")) is None))


def codex_restart(e):
    """What to do about an unstarted run (codex_unstarted): resume a later turn again, or rerun a
    first one, which mints a new run id."""
    return (f"run codex-delegate resume {e.get('run_id')} again" if e.get("thread_id")
            else "run codex-delegate run again; it gets a new run id")


def find_codex(key):
    """The folded codex entry whose run_id or thread_id is `key`, or None."""
    for (runner, _), e in fold(read_rows()).items():
        if runner == "codex" and key in (e.get("run_id"), e.get("thread_id")):
            return e
    return None


def codex_stopped(e):
    """(verdict, why) from a codex run's stop row: done when its `exit` is 0, else failed."""
    if e.get("exit") == 0:
        return "done", f"codex run {e.get('run_id')} ends"
    return "failed", f"codex run {e.get('run_id')} stopped with exit {e.get('exit')}"


# A watch is one long wait, at watches/<id>.json. A waiter writes it (`delegation-ledger wait`,
# or a codex-delegate wrapper for its own run) and the watch guard (a Stop hook) reads it, so
# these fields are the contract between them:
#   id, session_id, description, created
#                   set once; session_id is "unknown" when the waiter found no session
#   condition       what it waits for: {"codex": run_id} alone, or any of "pids" (a list of
#                   {"pid", "start", "comm"}: the procStart and command name seen when the
#                   wait began, since a pid unwatchable then is refused), "file", and "log"
#                   with "done" and "fail" (regexes) and "stale_min"; watch_verdict reads it
#   waiter_pid, waiter_start, waiter_heartbeat, poll_s
#                   the current waiter: its pid and procStart, its last poll (ISO), and the
#                   seconds between polls; waiter_alive reads them. A waiter heartbeats while it
#                   runs a codex finalize too
#   finalizing      {"pid", "start"} of the waiter that started `codex-delegate finalize` for
#                   a codex watch; absent before. Another waiter doesn't finalize while that
#                   pid is alive: it waits for the stop row
#   state           one of WATCH_STATES
#   blocked_at      when the guard blocked a stop on this lapse (ISO), else null; a waiter
#                   that takes the watch over, or polls it, clears it (unblock), and so does a
#                   guard that adopts it, which also reopens an acknowledged lapse
#   blocked_stop    a digest of the blocking stop's prompt_id and last_assistant_message
#                   (null when the payload had neither): twin guards in one stop get the same
#                   payload, a later stop doesn't
#   blocked_size    the session transcript's size in bytes at that block (null if unknown),
#                   the fallback when there is no blocked_stop; both are set and cleared with
#                   blocked_at
#   end_blocked_at  when the guard blocked a stop on an end it couldn't judge (ISO); absent
#                   before: a codex run that ended with its finalize owed, or a --log verdict
#                   that a line further back than the log's last 1 MB, which is all the guard
#                   reads, could change (the guard's `unseen`). It blocks on that once, even
#                   after the lapse was acknowledged, and unblock clears it with blocked_at. An
#                   end the guard can judge is recorded instead, which resolves the watch
#   session_id      a --resume moves the watch to the resuming session, unless it has none
#   claude_pid, claude_start
#                   the Claude Code process (claude_process) and its procStart that the waiter
#                   runs under, which its exit notifies; absent outside Claude Code. /clear
#                   keeps the process but starts a new session id, so that process's watch
#                   guard adopts the watch. After a crash and `claude --continue`, the new
#                   process's guard records itself here
#   waiter_unheard  true when the guard recorded itself as claude_pid while the waiter still
#                   ran under a process that had ended: that waiter's exit reaches nobody, so it
#                   may be taken over, and its end is reported by the guard. Taking the watch
#                   over clears it
#   waiter_detached true when the watch's waiter is, or was when it recorded the end, the
#                   guard's detached one: watch-guard starts it (spawn_waiter) when it
#                   acknowledges a lapse, double-forked away from the hook, with the guard's
#                   session and Claude process. Its exit reaches no one, so its end is recorded
#                   unreported, for the guard or the nudge to say; any other waiter may take the
#                   watch over from it, which clears the flag. Absent otherwise
#   detached_at     when the detached waiter took the watch (ISO), with waiter_detached: the
#                   guard starts another only after one that ran to DETACHED_MAX_MIN, so one
#                   that dies early isn't started again and again
#   end_why         how the waiter saw the condition end, the line it prints (`watch <id>
#                   failed: <why>`), set with the end: the guard says it for a detached
#                   waiter's end, whose output nobody reads
#   end_error       why the detached waiter stopped with no end (an error, or nothing it could
#                   decide), for the guard's next block to say; a waiter that takes the watch
#                   over clears it
#   ended           when it left UNRESOLVED (ISO); absent until then
#   reported        set when the watch ends: true once a live Claude Code process has heard
#                   how it ended (its waiter's Claude process ran when it recorded the end, or a
#                   guard or the session-start nudge said it), else false. A watch that ended
#                   before the field existed has none, and counts as reported
# open is waiting; acknowledged is a lapse the guard let a stop through on; done, failed and
# stale are how the waiter saw the condition end (it exits 0, 1, 2); dropped is `wait --drop`.
# Every change goes through update_watch, under watches/.lock, written atomically and only when
# something changed. Each wait start prunes temp files a crash left (over a day old) and
# watches that ended over 7 days ago.
#
# A codex watch: watch_verdict's "done" means Codex has ended, and unless the run has a stop
# row, a `codex-delegate finalize` is still owed. So the guard must not record a codex watch as
# done, since the run's outcome is unknown until it is finalized: it keeps the watch open and
# blocks once (end_blocked_at) saying to re-arm it, and the re-armed waiter finalizes the run
# and decides by the stop row's `exit` (0 done, else failed). A stop row with a nonzero exit is
# failed at once.
# A run that never started (its wrapper gone with its row still pending, and no codex.pid) is
# failed. When nothing can be decided (the run left the ledger; a finalize recorded no stop row),
# watch_verdict raises Undecidable or the waiter exits 70, and the watch stays open. A
# `codex-delegate resume` appends a pending row before Codex starts, so a waiter never mistakes
# the previous turn's stop row for this one's.
WATCH_STATES = ("open", "acknowledged", "done", "failed", "stale", "dropped")
UNRESOLVED = ("open", "acknowledged")  # the states a waiter may take over
ENDED = ("done", "failed", "stale", "dropped")
REPORTED_STATES = ("done", "failed", "stale")  # how a waiter ends; dropped is the lead's own
WAIT_POLL_S = 15  # the waiter's default seconds between polls
DETACHED_MAX_MIN = 24 * 60  # the guard's detached waiter's --max: no Bash cap applies to it
SCAN_CHUNK = 8 * 1024 * 1024  # scan_log reads a log this much at a time
MAX_WAIT_MIN = 110  # a waiter's ceiling: with a 5-minute finalize, under the 120-minute Bash cap
REARM = ("still running: re-arm with delegation-ledger wait --resume {} "
         "(run_in_background, timeout 7200000)")
PRUNE_TMP_DAYS, PRUNE_ENDED_DAYS = 1, 7
PF_KTHREAD = 0x00200000  # the per-process flags bit (stat field 9) of a kernel thread


class Undecidable(Exception):
    """A watch's condition can't be decided now (its codex run left the ledger, or a finalize
    recorded no stop row); nothing is recorded, so the watch stays open for a resume."""


def proc_comm(pid):
    """/proc/<pid>/comm, the process's command name, or None."""
    try:
        with open(f"/proc/{int(pid)}/comm") as f:
            return f.read().strip()
    except (OSError, TypeError, ValueError):
        return None


def unwatchable(pid):
    """Why a pid can't be a watch's job, or None. A sandboxed command's pids start at 1, so a
    pid echoed from one can name, outside, pid 1, a kernel thread or another user's daemon,
    none of which ends, or nothing at all."""
    fields = _stat_fields(pid)
    if fields is None or not pid_alive(pid):
        return "isn't running here"
    if int(pid) == 1:
        return "is the init process"
    try:
        kernel = int(fields[6]) & PF_KTHREAD  # field 9, counted from field 3 (state)
    except (ValueError, IndexError):
        kernel = 0
    if kernel:
        return "is a kernel thread"
    try:
        owner = os.stat(f"/proc/{int(pid)}").st_uid
    except OSError:
        return "isn't running here"
    return None if owner == os.getuid() else "belongs to another user"


def watch_path(wid):
    return _id_path(watches_dir(), wid, "a watch id")


def read_watch(wid):
    """The watch's dict, or None when there is none. A bad id or a damaged file raises
    ValueError."""
    try:
        with open(watch_path(wid)) as f:
            w = json.load(f)
    except FileNotFoundError:
        return None
    except ValueError as ex:  # a torn or hand-edited file
        raise ValueError(f"watch {wid}: damaged file ({ex})") from None
    if not isinstance(w, dict):
        raise ValueError(f"watch {wid}: damaged file (not a JSON object)")
    return w


def update_watch(wid, fn):
    """Read-modify-write a watch under watches/.lock, as update_agent_state does: fn gets the
    current dict ({} for a new watch) and changes it in place or returns a new one. The file
    is written only when fn changed it, so a no-op keeps its mtime (the prune clock). An error
    from fn (a waiter's StepAside, say) or from the write is raised."""
    out, failed = update_watches({wid: fn})
    if failed:
        raise failed[0][1]
    return out[wid]


def update_watches(fns, until=None, clock=time.monotonic):
    """update_watch for several watches ({wid: fn}) in one hold of watches/.lock. Returns
    ({wid: new}, [(wid, exception)]): one watch's error (a bad id, a damaged file, a full disk,
    or one fn raised) leaves that watch unwritten and the others go on. With `until`, the lock
    wait is bounded (LockBusy)."""
    out, failed = {}, []
    with dir_lock(watches_dir(), until, clock):
        for wid, fn in fns.items():
            try:
                cur = read_watch(wid) or {}
                before = copy.deepcopy(cur)
                new = fn(cur)
                new = cur if new is None else new
                if new != before:
                    write_json(watch_path(wid), new)
            except Exception as ex:  # noqa: BLE001  the caller decides; the rest go on
                failed.append((wid, ex))
                continue
            out[wid] = new
    return out, failed


def prune_watches():
    """Remove temp files a killed write left (over PRUNE_TMP_DAYS old) and watch files that
    ended (ENDED) over PRUNE_ENDED_DAYS ago, by mtime: a watch's last write is its end."""
    now = time.time()
    with dir_lock(watches_dir()):
        for p in glob.glob(os.path.join(watches_dir(), ".*.tmp")):
            with contextlib.suppress(OSError):
                if os.path.getmtime(p) < now - PRUNE_TMP_DAYS * 86400:
                    os.remove(p)
        for p in glob.glob(os.path.join(watches_dir(), "*.json")):
            with contextlib.suppress(OSError, ValueError):
                if os.path.getmtime(p) >= now - PRUNE_ENDED_DAYS * 86400:
                    continue
                with open(p) as f:
                    w = json.load(f)
                if isinstance(w, dict) and w.get("state") in ENDED:
                    os.remove(p)


def all_watches():
    """Every watch file that parses, oldest first."""
    out = []
    for p in glob.glob(os.path.join(watches_dir(), "*.json")):
        try:
            with open(p) as f:
                w = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(w, dict):
            out.append(w)
    return sorted(out, key=lambda w: str(w.get("created")))


def _pid_names(pids):
    """"pid 12 (sleep)" or "pids 12 (sleep), 13 (make)", so a wrong pid shows."""
    names = ", ".join(f"{p.get('pid')} ({p['comm']})" if p.get("comm") else str(p.get("pid"))
                      for p in pids)
    return f"pid {names}" if len(pids) == 1 else f"pids {names}"


def _clauses(c):
    """(key, clause) for each part of a condition that isn't a codex one."""
    out = []
    pids = c.get("pids") or []
    if pids:
        out.append(("pids", f"{_pid_names(pids)} {'exits' if len(pids) == 1 else 'exit'}"))
    if c.get("file"):
        out.append(("file", f"{c['file']} exists"))
    if c.get("done"):
        out.append(("done", f"{c['log']} has a line matching /{c['done']}/"))
    return out


def condition_text(c):
    """A watch's condition as a clause, like "pid 12 exits and /tmp/out exists"."""
    if "codex" in c:
        return f"codex run {c['codex']} ends"
    return " and ".join(text for _, text in _clauses(c))


def codex_progress(run_id):
    """(stage, entry) for a watched codex run: "stopped" when it has a stop row, "running"
    while Codex or its wrapper is alive (a live wrapper writes the stop row itself),
    "unstarted" when a pending row's wrapper died before Codex started (codex_unstarted:
    nothing to finalize), else "ended", with a finalize owed. Undecidable when the run is no
    longer in the ledger (it was there when the wait began)."""
    e = fold(read_rows()).get(("codex", run_id))
    if e is None:
        raise Undecidable(f"codex run {run_id} is no longer in the ledger ({ledger_path()})")
    if e.get("event") == "stop":
        return "stopped", e
    if codex_running(e) or codex_wrapper_alive(e):
        return "running", e
    if codex_unstarted(e):
        return "unstarted", e
    return "ended", e


def log_cursor():
    """A fresh scan_log cursor: how far the log has been read, whether a done line was seen,
    whether a fail line was, which file was read ((st_dev, st_ino), None before a read), and
    the last line with no newline yet, as the latest scan left it."""
    return {"offset": 0, "done": False, "failed": False, "file": None, "partial": ""}


def scan_log(path, done, fail, cursor, pids_gone=None, quiet_s=WAIT_POLL_S, now=None,
             settle=True, between=None):
    """Read the log from cursor["offset"] on: "failed" on a line matching `fail`, else "done"
    once a line has matched `done`, else None. Lines are matched once complete. The last line,
    with no newline yet, is left in cursor["partial"]; it may be a fragment whose writer hasn't
    flushed the rest, and an end-anchored pattern (`^OK$`, `error$`) could match the fragment
    alone. So it is matched only when `settle` and the job is over: the watch's pids are gone
    (`pids_gone`), or, for a watch with no pids (None), the log hasn't been modified for a poll
    (`quiet_s`) before `now`. That catches a writer still writing; one that pauses mid-line for
    longer than a poll can still be cut, so a final verdict (the guard's) passes settle=False.
    A log that shrank was rewritten in place, so it is read again from the start, and what was
    seen is forgotten. One that is another file than the one read (rotated by a rename, a
    symlink re-pointed) is read from its start too, but a line seen stays seen. The log is
    read SCAN_CHUNK at a time, so memory stays bounded, with `between()` called after each
    chunk (the waiter beats there). Each pattern is compiled once a scan."""
    try:
        f = open(path, "rb")
    except OSError:
        return None  # no log yet
    with f:
        st = os.fstat(f.fileno())
        ident = (st.st_dev, st.st_ino)
        if st.st_size < cursor["offset"]:
            cursor.update(offset=0, done=False)
        elif cursor["file"] not in (None, ident):
            cursor["offset"] = 0
        cursor["file"] = ident
        f.seek(cursor["offset"])
        fail_re, done_re = (re.compile(p) if p else None for p in (fail, done))
        carry = b""
        while True:
            chunk = f.read(SCAN_CHUNK)
            if not chunk:
                break
            whole, newline, carry = (carry + chunk).rpartition(b"\n")
            for line in whole.decode("utf-8", "replace").splitlines():
                if fail_re and fail_re.search(line):
                    cursor["failed"] = True
                    return "failed"
                if done_re and done_re.search(line):
                    cursor["done"] = True
            cursor["offset"] += len(whole) + len(newline)
            if between is not None:
                between()
    cursor["partial"] = partial = carry.decode("utf-8", "replace")
    now = time.time() if now is None else now
    settled = settle and (pids_gone if pids_gone is not None
                          else now - st.st_mtime >= quiet_s)
    if partial and settled:
        if fail_re and fail_re.search(partial):
            cursor["failed"] = True
            return "failed"
        if done_re and done_re.search(partial):
            return "done"
    return "done" if cursor["done"] else None


def watch_verdict(w, cursor=None, now=None, settle=True, between=None):
    """(verdict, why) for a watch's condition now: verdict is "done", "failed", "stale", or
    None while it still waits, and why says what it rests on. Every given part must hold for
    done; pids that all exited with another part unmet is failed. Pass the same `cursor` dict
    on every poll (log_cursor) to read a log incrementally; without one the whole log is read.
    For a codex watch, a stop row decides by its `exit`; with none, done means Codex and its
    wrapper are both gone (a live wrapper writes the stop row itself, and a finalize then would
    write a second one), and a finalize is still owed: see the comment above WATCH_STATES. A
    codex run that has left the ledger raises Undecidable."""
    c = w.get("condition") or {}
    now = time.time() if now is None else now
    if "codex" in c:
        stage, e = codex_progress(c["codex"])
        if stage == "stopped":
            return codex_stopped(e)
        if stage == "unstarted":  # a definite end: nothing ran, so nothing will finish
            return "failed", f"codex run {c['codex']} never started: {codex_restart(e)}"
        return (None if stage == "running" else "done"), condition_text(c)
    cursor = log_cursor() if cursor is None else cursor
    # The pids first: a job writes its file or its last log line before it exits, so a check
    # made after the exit can't miss them.
    pids = c.get("pids") or []
    running = [p for p in pids if pid_alive(p.get("pid"), p.get("start"))]
    poll = w.get("poll_s") if is_positive(w.get("poll_s")) else WAIT_POLL_S
    log = (scan_log(c["log"], c.get("done"), c.get("fail"), cursor,
                    pids_gone=not running if pids else None, quiet_s=poll, now=now,
                    settle=settle, between=between)
           if c.get("log") else None)
    if log == "failed":
        return "failed", f"{c['log']} has a line matching /{c['fail']}/"
    met = {"pids": not running, "file": bool(c.get("file")) and os.path.exists(c["file"]),
           "done": log == "done"}
    unmet = [text for key, text in _clauses(c) if not met[key]]
    if not unmet:
        return "done", condition_text(c)
    if pids and not running:
        return "failed", f"{_pid_names(pids)} exited, but {' and '.join(unmet)} is unmet"
    if c.get("stale_min"):
        try:
            changed = os.path.getmtime(c["log"])
        except OSError:
            changed = 0
        try:
            since = max(changed, parse_iso(w["created"]).timestamp())
        except (KeyError, TypeError, ValueError):
            since = now
        if now - since >= c["stale_min"] * 60:
            return "stale", f"{c['log']} unchanged for {c['stale_min']:g} min"
    return None, " and ".join(unmet)


def waiter_alive(w, now=None):
    """Whether the watch's waiter runs and polls: its pid with its procStart, and a heartbeat
    no older than two polls plus a second (the timestamp's resolution)."""
    now = time.time() if now is None else now
    if not pid_alive(w.get("waiter_pid"), w.get("waiter_start")):
        return False
    poll = w.get("poll_s") if is_positive(w.get("poll_s")) else WAIT_POLL_S
    try:
        return now - parse_iso(w["waiter_heartbeat"]).timestamp() <= 2 * poll + 1
    except (KeyError, TypeError, ValueError):
        return False


class WaitRefused(Exception):
    """Bad usage, or a watch a waiter can't take: `wait` exits 64 with this message, and
    codex-delegate refuses (exit 2)."""


class StepAside(Exception):
    """This waiter no longer owns its watch (taken over, dropped or deleted): `wait` exits 3,
    printing this message, and a codex-delegate wrapper stops heartbeating."""


def live_sessions():
    """sessionId -> pid for Claude processes that are still running. A session file's
    procStart must match the process too, so a reused pid doesn't keep a gone session alive."""
    out = {}
    for p in glob.glob(os.path.expanduser("~/.claude/sessions/*.json")):
        try:
            with open(p) as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        sid = d.get("sessionId") if isinstance(d, dict) else None
        if isinstance(sid, str) and sid and pid_alive(d.get("pid"), d.get("procStart")):
            out[sid] = d.get("pid")
    return out


def claude_identity():
    """(process, session): the Claude Code process this command runs under ((pid, procStart),
    or None) and its session id ("unknown" when none can be trusted), from one walk.
    CLAUDE_PID and CLAUDE_CODE_SESSION_ID are inherited, so on their own they can name another
    process's session: a nested `claude -p` started from the lead's Bash may carry the lead's,
    and a tmux server started from a Claude Bash call carries ones that go stale. So the
    ancestor walk decides (claude_ancestor):
    - it finds process A, CLAUDE_PID is A, and CLAUDE_CODE_SESSION_ID is set: A set both vars
      for this Bash call, so they are its own, and that id is the session. The env follows a
      session change (observed), and nothing verified says A's sessions file is rewritten
      before the first Bash call after /clear;
    - it finds A otherwise: A's sessions file names the session ("unknown" when it names
      none). The env can't: CLAUDE_PID isn't A, so the env may be another process's, or it
      names no session;
    - it finds nothing: the env counts only when CLAUDE_PID names an ancestor of this process,
      at any level. Then that is the process, and CLAUDE_CODE_SESSION_ID the session."""
    chain = ancestors()
    found = claude_ancestor(chain)
    try:
        env_pid = int(os.environ.get("CLAUDE_PID") or "")
    except ValueError:
        env_pid = None
    env_sid = os.environ.get("CLAUDE_CODE_SESSION_ID") or None
    if found is not None:
        pid, start, sid = found
        return (pid, start), (env_sid if env_pid == pid and env_sid else sid) or "unknown"
    if env_pid is None or env_pid not in chain:
        return None, "unknown"
    return (env_pid, proc_start(env_pid)), env_sid or "unknown"


def claude_process():
    """(pid, procStart) of the Claude Code process this command runs under (claude_identity),
    or None."""
    return claude_identity()[0]


def claude_alive(w):
    """Whether the Claude Code process a watch was recorded under (claude_pid with its
    claude_start) still runs. After /clear it runs on under a new session id, and its watch guard
    adopts the watch."""
    return w.get("claude_pid") is not None and pid_alive(w.get("claude_pid"),
                                                         w.get("claude_start"))


def left_by_clear(w, me, live):
    """Whether watch w was left in the Claude process `me` ((pid, procStart), or None): it was
    recorded under that process, in a session that isn't live (not in `live`, from
    live_sessions()). That is a watch from before a /clear, since the process runs on under a
    new session id and its sessions file names the new one, so the old id leaves the live set;
    or one recorded with no session ("unknown", never live). A live session's watch never
    counts, whatever the pids say: that session has it."""
    return (me is not None and w.get("claude_pid") == me[0]
            and str(w.get("claude_start")) == str(me[1]) and w.get("session_id") not in live)


def claude_gone(w):
    """Whether the Claude Code process a watch was recorded under has ended, so its waiter's
    exit reaches nobody, even when the session runs on in another process (a crash, then
    `claude --continue`)."""
    return w.get("claude_pid") is not None and not claude_alive(w)


def ended_unheard(w, now=None):
    """Whether watch w ended (REPORTED_STATES) in the last PRUNE_ENDED_DAYS while no Claude Code
    process was listening, and nobody has reported it since: `reported` is false, and its
    waiter was marked waiter_unheard or was the guard's detached one (whose exit reaches no
    one), or the Claude process it ran under has ended. A watch with no `reported` ended before
    the field existed, so it counts as reported and never shows. The watch guard of its session
    says it at a stop, the session-start nudge at the start of any session but its own, and the
    views (watch, open) until it is reported."""
    now = time.time() if now is None else now
    if (w.get("state") not in REPORTED_STATES or w.get("reported", True)
            or not (w.get("waiter_unheard") or w.get("waiter_detached") or claude_gone(w))):
        return False
    try:
        return now - parse_iso(w["ended"]).timestamp() <= PRUNE_ENDED_DAYS * 86400
    except (KeyError, TypeError, ValueError):
        return False


def watch_orphaned(w, current=None, live=None, now=None):
    """Whether nobody will hear from an unresolved watch's waiter, whatever its state. One the
    guard marked waiter_unheard is orphaned whatever its process: the guard that adopted it
    after a crash is alive, but the waiter's exit still goes to the process that ended. With a
    Claude process recorded, that process decides, whatever the session: gone (claude_gone),
    nobody hears its waiter's exit; alive, it does, and its guard adopts the watch (its own
    session's, or left_by_clear, which covers an "unknown" session too). With none recorded,
    the session decides: not while it is `current` (the caller's) or live. A watch with no
    session and no process was started outside Claude Code and reports to whoever ran it, so
    only a dead waiter orphans it. `live` is live_sessions(), if read."""
    if w.get("waiter_unheard"):
        return True
    if w.get("claude_pid") is not None:
        return not claude_alive(w)
    sid = w.get("session_id")
    if sid in (None, "unknown"):
        return not waiter_alive(w, now)
    if current and sid == current:
        return False
    return sid not in (live_sessions() if live is None else live)


def unblock(w):
    """Clear an unresolved watch's lapse record (blocked_at, blocked_stop, blocked_size,
    end_blocked_at) and its acknowledgment, so the guard's next block on it is a first one: a
    waiter that takes it over or polls it is live again, and a conversation that adopts it never
    saw the old block."""
    for key in ("blocked_size", "blocked_stop", "end_blocked_at"):
        w.pop(key, None)
    w.update(state="open", blocked_at=None)


def new_watch_id():
    return "w-" + time.strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)


def codex_watch(run_id):
    """The unresolved watch on a codex run, or None. There is one at most: a second is refused
    (Waiter.refuse_a_second_codex_watch)."""
    return next((w for w in all_watches() if w.get("state") in UNRESOLVED
                 and (w.get("condition") or {}).get("codex") == run_id), None)


class Waiter:
    """This process as one watch's waiter: it takes the watch over, heartbeats it, and records
    how it ended. Each write checks under the lock that it still owns the watch, and steps aside
    (StepAside) when it doesn't. `delegation-ledger wait` polls a condition with it, and a
    codex-delegate wrapper is the waiter of its own run's watch. `identity` is
    claude_identity(), found once per command, so the watch's process and session come from
    the same walk; for a `detached` waiter (the guard's, after it acknowledged a lapse) it is
    the guard's, which the guard passed on."""

    def __init__(self, wid, poll, identity, detached=False):
        self.wid, self.poll, self.me = wid, poll, os.getpid()
        self.claude, self.session = identity
        self.start = proc_start(self.me)
        self.detached = detached

    def own(self, w):
        """Raise StepAside unless this waiter still owns the watch."""
        if not w:
            raise StepAside(f"watch {self.wid}'s file is gone, so there is nothing left to wait "
                            "on; this waiter stepped aside")
        if w.get("state") == "dropped":
            raise StepAside(f"watch {self.wid} was dropped; this waiter stepped aside")
        if w.get("waiter_pid") != self.me:
            raise StepAside(f"watch {self.wid} was taken over by pid {w.get('waiter_pid')} (a "
                            "--resume); this waiter stepped aside, and the watch goes on")

    def refuse_a_live_waiter(self, w):
        """WaitRefused when the watch's waiter is alive and someone will hear from it
        (watch_orphaned, which goes by the Claude process first): its process runs, whatever
        its session; with no process recorded, its session is the caller's or live; with
        neither, always. A waiter whose heartbeat went stale (a suspended VM, say) can still be
        taken over, and so can a live one nobody hears: the guard marked it waiter_unheard, its
        Claude process has ended, even in a session that runs on, or, with no process recorded,
        its session is gone. It steps aside at its next beat. So does the guard's detached
        waiter, which anyone may take over: a lead that re-arms wants the end itself."""
        if (waiter_alive(w) and not w.get("waiter_detached")
                and not watch_orphaned(w, self.session)):
            raise WaitRefused(f"watch {w.get('id')} already has a live waiter (pid "
                              f"{w.get('waiter_pid')}); it will notify its session")

    def refuse_a_second_codex_watch(self, new):
        """WaitRefused when any session already has an unresolved watch on new's codex run,
        since each watch's waiter could finalize it. Called under the watches lock, so two
        waits started together can't both pass."""
        run = new["condition"].get("codex")
        w = codex_watch(run) if run is not None else None
        if w is not None:
            self.refuse_a_live_waiter(w)
            raise WaitRefused(f"watch {w.get('id')} already waits on {run}: "
                              f"delegation-ledger wait --resume {w.get('id')}")

    def refuse_unless_left_to_the_guard(self, w):
        """For a detached waiter: WaitRefused unless the watch is as the guard left it when it
        started this waiter: acknowledged, in the guard's session, with no live waiter. A
        re-arm since, or a twin guard's detached waiter, has it."""
        if (w.get("state") != "acknowledged" or w.get("session_id") != self.session
                or waiter_alive(w)):
            raise WaitRefused(f"watch {self.wid} is no longer an acknowledged lapse with no "
                              f"waiter in session {self.session}, so no detached waiter is due")

    def take(self, new):
        """Become the watch's waiter, creating it from `new` when given."""
        def take(w):
            if new is not None:
                self.refuse_a_second_codex_watch(new)
                w.update(new)
            elif not w:
                raise WaitRefused(f"no watch {self.wid!r}")
            elif w.get("state") not in UNRESOLVED:
                raise WaitRefused(f"watch {self.wid} is {w.get('state')}; start a new wait")
            elif self.detached:
                self.refuse_unless_left_to_the_guard(w)
            else:
                self.refuse_a_live_waiter(w)
            # A resume moves the watch to the caller's session, so one a crashed session left
            # is guarded in the session that re-armed it; a caller with none leaves it be.
            if self.session != "unknown":
                w["session_id"] = self.session
            # The process this waiter's exit notifies, so its guard adopts the watch after a
            # /clear; none outside Claude Code, where the exit reaches whoever ran it.
            if self.claude is not None:
                w.update(claude_pid=self.claude[0], claude_start=self.claude[1])
            else:
                w.pop("claude_pid", None)
                w.pop("claude_start", None)
            w.pop("waiter_unheard", None)
            w.pop("end_error", None)
            if self.detached:
                w.update(waiter_detached=True, detached_at=now_iso())
            else:
                w.pop("waiter_detached", None)
                w.pop("detached_at", None)
            unblock(w)
            w.update(waiter_pid=self.me, waiter_start=self.start, poll_s=self.poll,
                     waiter_heartbeat=now_iso())
        return update_watch(self.wid, take)

    def beat(self):
        """Refresh the heartbeat. A waiter that polls is live, so a lapse the guard saw meanwhile
        is over."""
        def beat(w):
            self.own(w)
            if w.get("state") in UNRESOLVED:
                unblock(w)
                w["waiter_heartbeat"] = now_iso()
        return update_watch(self.wid, beat)

    def end(self, verdict, why=None):
        """Record how the watch ended: done, failed or stale, `why` (end_why), and whether it's
        reported: true when this waiter's exit notifies a live Claude process, else false. A
        detached waiter's notifies no one."""
        def end(w):
            self.own(w)
            w.update(state=verdict, ended=now_iso(),
                     reported=(claude_alive(w) and not w.get("waiter_unheard")
                               and not w.get("waiter_detached")))
            if why:
                w["end_why"] = why
        return update_watch(self.wid, end)

    def fail(self, why):
        """Record why this waiter stops with no end (end_error), while it still owns the
        watch: a detached waiter's error reaches no one otherwise."""
        def fail(w):
            self.own(w)
            w["end_error"] = why
        return update_watch(self.wid, fail)
