"""Shared pieces for delegation-ledger and codex-delegate (stdlib only).

The ledger is an append-only JSONL file of pointers, never content: ids, types, paths,
exit codes, and whether a report validated. Briefs and outputs stay in the transcripts
and rollouts they already live in.
"""
import datetime
import fcntl
import json
import os
import re
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


def read_rows():
    try:
        with open(ledger_path()) as f:
            lines = f.readlines()
    except FileNotFoundError:
        return []
    rows = []
    for line in lines:
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


def pid_alive(pid):
    try:
        return pid is not None and os.path.exists(f"/proc/{int(pid)}")
    except (TypeError, ValueError):
        return False


def codex_state(e):
    """(verdict, evidence) for a folded codex ledger entry, shared by `delegation-ledger
    open` and `codex-delegate status`. Codex writes its events straight to the file, so it
    can outlive a wrapper that was killed (Claude's Bash tool stops a foreground command at
    10 minutes); a run with no stop row is therefore not necessarily dead."""
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
    evidence = (f"codex pid {e.get('pid')} {'alive' if codex_alive else 'gone'}, "
                f"wrapper {'alive' if wrapper_alive else 'gone'}, "
                + (f"last event {age:.0f} min ago" if age is not None else "no events file")
                + (", report.json present" if has_report else ""))
    return verdict, evidence
