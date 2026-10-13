"""stop-ring's event reader: the facts the shim needs, and the session's stop record.

hooks/stop-ring.sh runs this file with python3 -I, passing the Stop event on stdin, and reads one
line back: "<spawned> <busy> <task labels or -> <transcript size or -> <transcript path>". The
shim's header says what each means; with this file missing or failing, the shim reads nothing
and rings by its defaults. Tests import merge_replies() and prune() directly
(tests/setup/test_tmux_hooks.py). Stdlib only; keep the source ASCII.

The stop record, $XDG_STATE_HOME/dotclaude/stops/<session>.json, is written atomically for every
stop but a subagent's, and only for a session id that is a plain name. It holds the time, the
waits in flight (labels), every task as {label, id, description, url} (task_entries: the label
is `unlabeled` for one with none, `monitor` for a Monitor the payload labels `shell`, and
`artifact watch` for the Artifact tool's live watch: task_types), the transcript path when it
is a string, and `replies`: what Claude said in the last TURNS turns, for the banner and popup
after a plain /pass (pass-respawn copies it to pass-last/). A turn is a run of replies with one
prompt_id: a Stop a hook blocked and the Stop that ends the continued turn carry the same one
(spike A5). The payload can't tell a typed prompt from a turn a background-task notice started,
so a turn is not always one of Hayden's prompts. A `claude -p` run
(CLAUDE_CODE_SESSION_ATTENDED=0) never passes, so its record has no `replies`.
"""
import glob
import json
import mmap
import os
import re
import sys
import tempfile
import time
import unicodedata

WAITS = {"subagent", "shell", "workflow", "cloud session"}
ID = re.compile(r"[A-Za-z0-9_-]{1,128}")   # a task or tool-use id we search the transcript for
SID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
# The live watch the Artifact tool arms on each publish (2.1.296: a monitor_ws flagged ambient).
# Claude Code keeps it out of /tasks and its own busy counts and never shows the model its id,
# but the Stop payload lists it as a `monitor` with no server, described by this prefix, the
# page's URL and what it delivers. The canary checks the prefix is still in the binary
# (delegation_checks.CANARY_STRINGS).
ARTIFACT_WATCH_PREFIX = "live updates for artifact "
ARTIFACT_WATCH = re.compile(re.escape(ARTIFACT_WATCH_PREFIX)
                            + r"(https://claude\.ai/(?:code/)?artifact/[A-Za-z0-9_-]{1,128})(?=\s|$)")
DESC_CAP = 200             # characters of a task's description kept in the stop record
TEXT_CAP = 64 * 1024       # bytes of UTF-8 per reply
TOTAL_CAP = 128 * 1024     # bytes of UTF-8 over all replies; the oldest turns go first
TURNS = 5                  # the most recent turns (runs of one prompt_id) kept
PRUNE_AGE, PRUNE_EVERY = 7 * 86400, 86400


def utf8(text: str) -> str:
    """text as valid UTF-8 can carry it: a lone surrogate becomes '?'."""
    return text.encode("utf-8", "replace").decode("utf-8")


def size(text: str) -> int:
    return len(text.encode("utf-8"))


def cut(text: str) -> str:
    """text cut to TEXT_CAP bytes of UTF-8 on a character boundary, with a one-line note."""
    raw = utf8(text).encode("utf-8")
    if len(raw) <= TEXT_CAP:
        return raw.decode("utf-8")
    note = "\n[cut to 64 KiB: the reply was %d bytes]" % len(raw)
    return raw[:TEXT_CAP - len(note)].decode("utf-8", "ignore") + note


def runs(replies: list) -> list[list]:
    """The replies split into turns: runs of one prompt_id, oldest first."""
    out = []
    for r in replies:
        if out and out[-1][0]["prompt_id"] == r["prompt_id"]:
            out[-1].append(r)
        else:
            out.append([r])
    return out


def total(replies: list) -> int:
    return sum(size(r["text"]) for r in replies)


def dropped_note(prompt_id: str, count: int, when) -> dict:
    return {"prompt_id": prompt_id, "dropped": count, "time": when,
            "text": "[%d earlier repl%s of this turn dropped: over 128 KiB]"
                    % (count, "y" if count == 1 else "ies")}


def fit(replies: list) -> list:
    """replies within TOTAL_CAP: whole older turns go first. If the newest turn alone is still
    over, its oldest replies go and a note leads the turn, counting them (it keeps the count
    across Stops)."""
    turns = runs(replies)
    while len(turns) > 1 and total([r for t in turns for r in t]) > TOTAL_CAP:
        turns.pop(0)
    kept = [r for t in turns for r in t]
    if total(kept) <= TOTAL_CAP:
        return kept
    turn = turns[0]  # the newest turn, alone and over the cap
    count, when = 0, None
    if isinstance(turn[0].get("dropped"), int):
        count, when = turn[0]["dropped"], turn[0].get("time")
        turn = turn[1:]
    room = TOTAL_CAP - size(dropped_note("", 10 ** 6, None)["text"])
    while len(turn) > 1 and total(turn) > room:
        gone = turn.pop(0)
        count += 1
        when = when if when is not None else gone.get("time")
    return [dropped_note(turn[0]["prompt_id"], count, when), *turn]


def merge_replies(previous, message, prompt_id, now: float) -> list:
    """The record's new `replies`: the previous record's valid entries plus this Stop's reply,
    skipped when it repeats the newest entry (same text, same prompt_id). Then only the TURNS
    most recent turns stay, within TOTAL_CAP (fit). A Stop with no prompt_id (not a string, or
    empty) gets a turn of its own, "none-<time>", so it never joins another Stop's."""
    replies = previous if isinstance(previous, list) else []
    replies = [{**({"dropped": r["dropped"]} if isinstance(r.get("dropped"), int) else {}),
                "prompt_id": r["prompt_id"], "text": utf8(r["text"]), "time": r.get("time")}
               for r in replies if isinstance(r, dict) and isinstance(r.get("prompt_id"), str)
               and isinstance(r.get("text"), str) and r["text"].strip()]
    group = prompt_id if isinstance(prompt_id, str) and prompt_id else "none-%.6f" % now
    if isinstance(message, str) and message.strip():
        text = cut(message)
        if not (replies and replies[-1]["text"] == text and replies[-1]["prompt_id"] == group):
            replies.append({"prompt_id": group, "text": text, "time": now})
    replies = [r for t in runs(replies)[-TURNS:] for r in t]
    return fit(replies)


def prune(directory: str, now: float) -> None:
    """Delete the directory's *.json files older than PRUNE_AGE, at most once per PRUNE_EVERY
    (the mtime of its .pruned stamp). Best-effort: any error leaves things as they are."""
    stamp = os.path.join(directory, ".pruned")
    try:
        if now - os.path.getmtime(stamp) < PRUNE_EVERY:
            return
    except OSError:
        pass
    try:
        with open(stamp, "a"):
            pass
        os.utime(stamp, (now, now))
    except OSError:
        return
    for path in glob.glob(os.path.join(directory, "*.json")):
        try:
            if now - os.path.getmtime(path) > PRUNE_AGE:
                os.unlink(path)
        except OSError:
            pass


def load(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _line_at(m, pos: int):
    """(start offset, parsed object) of the line in mmap m that holds byte pos; None on a parse
    miss."""
    start = m.rfind(b"\n", 0, pos) + 1
    end = m.find(b"\n", pos)
    try:
        return start, json.loads(m[start:end if end >= 0 else len(m)])
    except ValueError:
        return start, None


def _answers_monitor(m, pos: int, task_id: str) -> bool:
    """Whether the line of m holding byte pos is a result (toolUseResult.taskId == task_id)
    answering a Monitor call made earlier in the same file."""
    start, d = _line_at(m, pos)
    result = d.get("toolUseResult") if isinstance(d, dict) else None
    msg = d.get("message") if isinstance(d, dict) else None
    content = msg.get("content") if isinstance(msg, dict) else None
    if not (isinstance(result, dict) and result.get("taskId") == task_id
            and isinstance(content, list)):
        return False
    for c in content:
        use = c.get("tool_use_id") if isinstance(c, dict) and c.get("type") == "tool_result" \
            else None
        if not (isinstance(use, str) and ID.fullmatch(use)):
            continue
        at = m.rfind(b'"id":"' + use.encode() + b'"', 0, start)
        _, call = _line_at(m, at) if at >= 0 else (0, None)
        msg = call.get("message") if isinstance(call, dict) else None
        for u in msg.get("content") if isinstance(msg, dict) and \
                isinstance(msg.get("content"), list) else []:
            if isinstance(u, dict) and u.get("type") == "tool_use" and u.get("id") == use \
                    and u.get("name") == "Monitor":
                return True
    return False


def _settle(m, wanted: set) -> dict:
    """{id: True when a Monitor started it, False when a background Bash command did} for the
    ids in wanted that m settles, from one backward walk over m's task-id keys: "taskId" (a
    Monitor's result) and "backgroundTaskId" (a Bash command's) both end in `askId":"<id>"`,
    which only a real key matches (a quote inside a string value is escaped). A walk stops as
    soon as every id is settled, so recent tasks cost little; a "taskId" hit that isn't a
    Monitor's result doesn't settle its id, and the walk goes on past it."""
    out, pos = {}, len(m)
    while len(out) < len(wanted):
        pos = m.rfind(b'askId":"', 0, pos)
        if pos < 0:
            break
        close = m.find(b'"', pos + 8, pos + 8 + 130)
        task_id = m[pos + 8:close].decode("ascii", "replace") if close > 0 else ""
        if task_id not in wanted or task_id in out:
            continue
        if m[max(0, pos - 12):pos] == b'"backgroundT':
            out[task_id] = False
        elif m[max(0, pos - 2):pos] == b'"t' and _answers_monitor(m, pos, task_id):
            out[task_id] = True
    return out


def monitor_ids(path, wanted, budget: float = 2.0) -> set:
    """Which task ids in wanted the Monitor tool started, from the transcript and then its
    subagents' transcripts (<session>/subagents/*.jsonl): an id one file settles (_settle)
    isn't looked for in the next, so a Monitor started early in a long session, or by a
    subagent, still counts. Claude Code 2.1.296 writes compact JSON (`"taskId":"<id>"`). The
    subagents' files are skipped once budget seconds have gone, so a cold read of several big
    files can't run the Stop hook out of time. Ids that aren't plain names are skipped."""
    left = {i for i in wanted if isinstance(i, str) and ID.fullmatch(i)}
    found = set()
    if not left or not isinstance(path, str) or "\n" in path:
        return found
    deadline = time.monotonic() + budget
    base = path[:-len(".jsonl")] if path.endswith(".jsonl") else path
    for k, name in enumerate([path, *sorted(glob.glob(os.path.join(
            glob.escape(base), "subagents", "*.jsonl")))]):
        if k and time.monotonic() > deadline:
            break
        try:
            with open(name, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
                settled = _settle(m, left)
        except (OSError, ValueError):   # unreadable, or empty (mmap refuses size 0)
            continue
        found |= {i for i, monitor in settled.items() if monitor}
        left -= set(settled)
        if not left:
            break
    return found


def artifact_url(task):
    """The page's URL when task (a background_tasks entry) is the Artifact tool's live watch: a
    `monitor` with no server (an MCP monitor names one) whose description opens with
    ARTIFACT_WATCH. Else None. A Monitor the model started with that very description would
    pass too; nothing in the payload tells them apart, so the model would have to name it so."""
    if not (isinstance(task, dict) and task.get("type") == "monitor" and "server" not in task):
        return None
    desc = task.get("description")
    m = ARTIFACT_WATCH.match(desc) if isinstance(desc, str) else None
    return m.group(1) if m else None


def task_types(tasks, path) -> list:
    """Each background_tasks entry's type, in order (None for one that isn't an object), with a
    `shell` task the Monitor tool started as `monitor`, and the Artifact tool's live watch as
    `artifact watch` (artifact_url). The Stop payload labels a Monitor `shell`, like a
    background Bash command (spike A10), and a shell is work the turn waits on while a monitor
    is not, so only the transcript tells them apart. It is searched only for the shell tasks
    listed; any failure there leaves them `shell` (the old behavior)."""
    if not isinstance(tasks, list):
        return []
    shells = [t.get("id") for t in tasks if isinstance(t, dict) and t.get("type") == "shell"
              and isinstance(t.get("id"), str)]
    try:
        monitors = monitor_ids(path, shells) if shells else set()
    except Exception:
        monitors = set()
    return [("monitor" if t.get("type") == "shell" and isinstance(t.get("id"), str)
             and t.get("id") in monitors
             else "artifact watch" if artifact_url(t) else t.get("type"))
            if isinstance(t, dict) else None
            for t in tasks]


def clean(text):
    """A task's description as one plain line for a notice, a log line and the model: control
    and format characters dropped (an escape sequence, a bidi override), whitespace folded to
    single spaces, double quotes made single (the notice quotes it), cut to DESC_CAP characters.
    None for no text."""
    if not isinstance(text, str):
        return None
    kept = "".join(" " if c.isspace() else c for c in utf8(text)
                   if c.isspace() or unicodedata.category(c) not in ("Cc", "Cf"))
    line = " ".join(kept.replace('"', "'").split())
    if len(line) > DESC_CAP:
        line = line[:DESC_CAP - 3] + "..."
    return line or None


def task_entries(tasks: list, labels: list) -> list:
    """The stop record's `tasks`: per background_tasks entry, {label} plus its id when that is a
    plain name, its description (clean) and an artifact watch's url. pass-respawn names them
    in a refusal and `pass-respawn --tasks` lists them, so the session can stop one by id."""
    out = []
    for t, k in zip(tasks, labels):
        e = {"label": k if isinstance(k, str) and k else "unlabeled"}
        if isinstance(t, dict):
            if isinstance(t.get("id"), str) and ID.fullmatch(t["id"]):
                e["id"] = t["id"]
            if desc := clean(t.get("description")):
                e["description"] = desc
            if url := artifact_url(t):
                e["url"] = url
        out.append(e)
    return out


def write_record(d: dict, sid: str, types: list, tasks: list) -> None:
    stops = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude", "stops")
    os.makedirs(stops, exist_ok=True)
    path = os.path.join(stops, sid + ".json")
    now = time.time()
    rec = {"session_id": sid, "time": now, "waits": [t for t in types if t in WAITS],
           "tasks": tasks}
    if isinstance(d.get("transcript_path"), str):
        rec["transcript_path"] = d["transcript_path"]
    if os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") != "0":
        previous = load(path)
        rec["replies"] = merge_replies(
            previous.get("replies") if isinstance(previous, dict) else None,
            d.get("last_assistant_message"), d.get("prompt_id"), now)
    data = json.dumps(rec, ensure_ascii=False).encode("utf-8", "replace")
    fd, tmp = tempfile.mkstemp(dir=stops, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    prune(stops, now)


def main() -> None:
    try:
        d = json.load(sys.stdin.buffer)
    except Exception:
        d = {}
    if not isinstance(d, dict):
        d = {}
    spawned = 1 if (d.get("agent_id") or d.get("agent_type")) else 0
    raw = d.get("background_tasks")
    raw = raw if isinstance(raw, list) else []
    tasks = task_types(raw, d.get("transcript_path"))   # one per entry, a Monitor as `monitor`
    types = [k for k, t in zip(tasks, raw) if isinstance(t, dict)]
    busy = 1 if any(t in WAITS for t in types) else 0
    sid = d.get("session_id")
    if not spawned and isinstance(sid, str) and SID.fullmatch(sid):
        try:
            write_record(d, sid, types, task_entries(raw, tasks))
        except Exception:
            pass
    labels = ",".join(t.replace(" ", "_") for t in types if isinstance(t, str) and t.strip())
    path = d.get("transcript_path")
    try:
        tsize = os.path.getsize(path) if isinstance(path, str) and "\n" not in path else "-"
    except (OSError, ValueError):
        tsize = "-"
    print(spawned, busy, labels or "-", tsize, path if tsize != "-" else "")


if __name__ == "__main__":
    main()
