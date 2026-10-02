"""Shared pieces for the delegation scripts (stdlib only): the ledger, the liveness index, the
policy path and the [deadline] helpers.

The ledger is an append-only JSONL file of pointers, never content: ids, types, paths,
exit codes, and whether a report validated. Briefs and outputs stay in the transcripts
and rollouts they already live in.

Beside it, agents/<id>.json is the per-agent liveness index: the latest state of each Claude
agent, rewritten at its starts and stops (and once per activation by the deadline nudge), so a
reader gets one agent's state without folding the whole ledger.

watches/<id>.json is a long wait that `delegation-ledger wait` records and the watch guard (a
Stop hook) reads; the comment above WATCH_STATES documents its fields.
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


@contextlib.contextmanager
def dir_lock(directory):
    """An exclusive flock on <directory>/.lock, which read-modify-writes there hold."""
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


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
    exclusions)."""
    out = {}
    for r in rows:
        key = (r.get("runner"), r.get("id"))
        if key[1] is None or r.get("event") in NOT_LIFECYCLE:
            continue  # a denial or a nudge, not a lifecycle event
        first = out.get(key, {}).get("first_ts", r.get("ts"))
        merged = dict(out.get(key, {}))
        merged.update(r)  # None overrides too: a clean resume must clear an old error
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


def pids_visible():
    """False when this process can't see its own Claude session's pid. Claude Code sets
    CLAUDE_PID in the Bash tool's env, and that process is alive by definition, so not seeing
    it means a sandbox PID namespace (each sandboxed command gets its own), where no pid check
    means anything. True when CLAUDE_PID is unset (tmux, a plain terminal)."""
    pid = os.environ.get("CLAUDE_PID")
    return not pid or pid_alive(pid)


def codex_state(e, visible=True):
    """(verdict, evidence) for a folded codex ledger entry, shared by `delegation-ledger
    open` and `watch` and by `codex-delegate status`. Codex writes its events straight to the file, so it
    can outlive a wrapper that was killed (Claude's Bash tool stops a foreground command at
    10 minutes); a run with no stop row is therefore not necessarily dead. With `visible`
    False (see pids_visible), the pid checks mean nothing, so it says that instead."""
    event = e.get("event")
    out = e.get("out") or ""
    events = os.path.join(out, "events.jsonl")
    age = ((time.time() - os.path.getmtime(events)) / 60) if os.path.exists(events) else None
    codex_alive = pid_alive(e.get("pid"))
    wrapper_alive = pid_alive(e.get("wrapper_pid"))
    has_report = os.path.exists(os.path.join(out, "report.json"))
    run = e.get("run_id")
    if event == "stop":
        verdict = "finished"
    elif not visible:
        verdict = "pid not visible in the sandbox"
    elif codex_alive:
        verdict = "running" + ("" if wrapper_alive else " (its wrapper is gone; "
                               f"`codex-delegate finalize {run}` once it ends)")
    elif event == "pending":
        verdict = ("starting" if wrapper_alive else
                   "never started a thread: rerun it with `codex-delegate run`")
    elif has_report:
        verdict = f"ended without a stop row: `codex-delegate finalize {run}`"
    else:
        verdict = f"died: `codex-delegate resume {run}`"
    pids = (f"codex pid {e.get('pid')} {'alive' if codex_alive else 'gone'}, "
            f"wrapper {'alive' if wrapper_alive else 'gone'}" if visible else
            f"codex pid {e.get('pid')} and its wrapper not visible in the sandbox")
    evidence = (f"{pids}, "
                + (f"last event {age:.0f} min ago" if age is not None else "no events file")
                + (", report.json present" if has_report else ""))
    return verdict, evidence


def codex_live(e):
    """Whether a folded codex entry's run is still going: its Codex pid runs, or a pending
    row's wrapper does (Codex hasn't started a thread yet)."""
    return pid_alive(e.get("pid")) or (e.get("event") == "pending"
                                       and pid_alive(e.get("wrapper_pid")))


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


# A watch is one long wait, at watches/<id>.json. `delegation-ledger wait` writes it and the
# watch guard (a Stop hook) reads it, so these fields are the contract between them:
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
#                   that takes the watch over, or polls it, clears it
#   ended           when it left UNRESOLVED (ISO); absent until then
# open is waiting; acknowledged is a lapse the guard let a stop through on; done, failed and
# stale are how the waiter saw the condition end (it exits 0, 1, 2); dropped is `wait --drop`.
# Every change goes through update_watch, under watches/.lock, written atomically and only when
# something changed. Each wait start prunes temp files a crash left (over a day old) and
# watches that ended over 7 days ago.
#
# A codex watch: watch_verdict's "done" means Codex has ended, and unless the run has a stop
# row, a `codex-delegate finalize` is still owed. So the guard must not record a codex watch as
# done; it sends the lead to `wait --resume`, whose waiter finalizes and then decides by the
# stop row's `exit` (0 done, else failed). A stop row with a nonzero exit is failed at once.
# When nothing can be decided (the run left the ledger; a finalize recorded no stop row),
# watch_verdict raises Undecidable or the waiter exits 70, and the watch stays open.
# Known gap until T3: `codex-delegate resume` writes no row until Codex's thread.started, so a
# `wait --codex` started in that window sees the previous run's stop row and ends at once.
WATCH_STATES = ("open", "acknowledged", "done", "failed", "stale", "dropped")
UNRESOLVED = ("open", "acknowledged")  # the states a waiter may take over
ENDED = ("done", "failed", "stale", "dropped")
WAIT_POLL_S = 15  # the waiter's default seconds between polls
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
    is written only when fn changed it, so a no-op keeps its mtime (the prune clock)."""
    path = watch_path(wid)
    with dir_lock(watches_dir()):
        cur = read_watch(wid) or {}
        before = copy.deepcopy(cur)
        new = fn(cur)
        new = cur if new is None else new
        if new != before:
            write_json(path, new)
    return new


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
    while Codex or its wrapper is alive (a live wrapper writes the stop row itself), else
    "ended", with a finalize owed. Undecidable when the run is no longer in the ledger (it was
    there when the wait began)."""
    e = fold(read_rows()).get(("codex", run_id))
    if e is None:
        raise Undecidable(f"codex run {run_id} is no longer in the ledger ({ledger_path()})")
    if e.get("event") == "stop":
        return "stopped", e
    if pid_alive(e.get("pid")) or pid_alive(e.get("wrapper_pid")):
        return "running", e
    return "ended", e


def log_cursor():
    """A fresh scan_log cursor: how far the log has been read, whether a done line was seen,
    and the log's size at the previous scan."""
    return {"offset": 0, "done": False, "size": None}


def scan_log(path, done, fail, cursor, pids_gone=None):
    """Read the log from cursor["offset"] on: "failed" on a line matching `fail`, else "done"
    once a line has matched `done`, else None. Lines are matched once complete. A last line
    with no newline yet may still be being written, so it is matched only once the job is over:
    when the watch's pids are gone (`pids_gone`), or, for a watch with no pids (None), when the
    log's size hasn't changed since the previous scan. A log that shrank (rewritten or rotated)
    is read again from the start."""
    try:
        with open(path, "rb") as f:
            size = os.fstat(f.fileno()).st_size
            if size < cursor["offset"]:
                cursor.update(offset=0, done=False)
            f.seek(cursor["offset"])
            data = f.read()
    except OSError:
        return None  # no log yet
    settled = pids_gone if pids_gone is not None else size == cursor["size"]
    cursor["size"] = size
    whole, newline, partial = data.rpartition(b"\n")
    cursor["offset"] += len(whole) + len(newline)
    lines = [(line, True) for line in whole.decode("utf-8", "replace").splitlines()]
    if partial and settled:
        lines.append((partial.decode("utf-8", "replace"), False))
    seen = False
    for line, consumed in lines:
        if fail and re.search(fail, line):
            return "failed"
        if done and re.search(done, line):
            seen = True
            cursor["done"] = cursor["done"] or consumed
    return "done" if seen or cursor["done"] else None


def watch_verdict(w, cursor=None, now=None):
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
        return (None if stage == "running" else "done"), condition_text(c)
    cursor = log_cursor() if cursor is None else cursor
    # The pids first: a job writes its file or its last log line before it exits, so a check
    # made after the exit can't miss them.
    pids = c.get("pids") or []
    running = [p for p in pids if pid_alive(p.get("pid"), p.get("start"))]
    log = (scan_log(c["log"], c.get("done"), c.get("fail"), cursor,
                    pids_gone=not running if pids else None) if c.get("log") else None)
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
