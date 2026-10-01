"""Shared pieces for delegation-ledger and codex-delegate (stdlib only).

The ledger is an append-only JSONL file of pointers, never content: ids, types, paths,
exit codes, and whether a report validated. Briefs and outputs stay in the transcripts
and rollouts they already live in.

Beside it, agents/<id>.json is the per-agent liveness index: the latest state of each Claude
agent, rewritten at its starts and stops, so a reader gets one agent's state without folding
the whole ledger.
"""
import contextlib
import datetime
import fcntl
import glob
import json
import os
import re
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
SCHEMA_PATH = os.path.join(os.path.dirname(HERE), "report.schema.json")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=datetime.timezone.utc)


def state_dir():
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
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


def _agent_path(aid):
    aid = str(aid)
    if not aid or aid.startswith(".") or os.path.basename(aid) != aid:
        raise ValueError(f"not an agent id: {aid!r}")
    return os.path.join(agents_dir(), f"{aid}.json")


@contextlib.contextmanager
def _agents_lock():
    os.makedirs(agents_dir(), exist_ok=True)
    with open(os.path.join(agents_dir(), ".lock"), "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


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
    with _agents_lock():
        cur = read_agent_state(aid)
        new = fn(cur)
        new = cur if new is None else new
        fd, tmp = tempfile.mkstemp(dir=agents_dir(), prefix=f".{aid}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(new, f, sort_keys=True)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise
    return new


def prune_agent_states(days=7):
    """Remove index files (and temp files a crash left) whose mtime is over `days` old. They
    are program-owned: an agent's file is written only at its starts and stops."""
    cutoff = time.time() - days * 86400
    with _agents_lock():
        for p in (glob.glob(os.path.join(agents_dir(), "*.json"))
                  + glob.glob(os.path.join(agents_dir(), ".*.tmp"))):
            with contextlib.suppress(OSError):
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)


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


def fold(rows):
    """Latest row per (runner, id), plus the first-seen timestamp. SubagentStart fires on
    every teammate message, so an id can have many start/stop pairs; the latest wins.
    subagent-policy's `policy` rows are skipped here (tail and audit show them)."""
    out = {}
    for r in rows:
        key = (r.get("runner"), r.get("id"))
        if key[1] is None or r.get("event") == "policy":
            continue  # a policy row records a denial, not a lifecycle event
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
    tp, aid = data.get("transcript_path") or "", str(data.get("agent_id") or "")
    if not tp or not aid:
        return {}
    aid = aid[len("agent-"):] if aid.startswith("agent-") else aid
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


def proc_start(pid):
    """Field 22 of /proc/<pid>/stat (starttime, in clock ticks since boot), or None. The
    fields are split after the last ") ", since the command name may hold spaces."""
    try:
        with open(f"/proc/{int(pid)}/stat") as f:
            return int(f.read().rsplit(") ", 1)[1].split()[19])
    except (OSError, TypeError, ValueError, IndexError):
        return None


def pid_alive(pid, start=None):
    """Whether pid is running. Given `start` (a session file's procStart), the process must
    also have that start time, so a pid the kernel reused for another process reads as gone.
    No `start` means don't check it."""
    try:
        if pid is None or not os.path.exists(f"/proc/{int(pid)}"):
            return False
    except (TypeError, ValueError):
        return False
    return start is None or str(proc_start(pid)) == str(start)


def pids_visible():
    """False when this process can't see its own Claude session's pid. Claude Code sets
    CLAUDE_PID in the Bash tool's env, and that process is alive by definition, so not seeing
    it means a sandbox PID namespace (each sandboxed command gets its own), where no pid check
    means anything. True when CLAUDE_PID is unset (tmux, a plain terminal)."""
    pid = os.environ.get("CLAUDE_PID")
    return not pid or pid_alive(pid)


def codex_state(e, visible=True):
    """(verdict, evidence) for a folded codex ledger entry, shared by `delegation-ledger
    open` and `codex-delegate status`. Codex writes its events straight to the file, so it
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
