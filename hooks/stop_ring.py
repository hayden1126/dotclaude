"""stop-ring's event reader: the facts the shim needs, and the session's stop record.

hooks/stop-ring.sh runs this file with python3 -I, passing the Stop event on stdin, and reads one
line back: "<spawned> <busy> <task labels or -> <transcript size or -> <transcript path>". The
shim's header says what each means; with this file missing or failing, the shim reads nothing
and rings by its defaults. Tests import merge_replies() and prune() directly
(tests/setup/test_tmux_hooks.py). Stdlib only; keep the source ASCII.

The stop record, $XDG_STATE_HOME/dotclaude/stops/<session>.json, is written atomically for every
stop but a subagent's, and only for a session id that is a plain name. It holds the time, the
waits in flight, every task's label (`unlabeled` for one with none), the transcript path when it
is a string, and `replies`: what Claude said in the last TURNS turns, for the banner and popup
after a plain /pass (pass-respawn copies it to pass-last/). A turn is a run of replies with one
prompt_id: a Stop a hook blocked and the Stop that ends the continued turn carry the same one
(spike A5). The payload can't tell a typed prompt from a turn a background-task notice started,
so a turn is not always one of Hayden's prompts. A `claude -p` run
(CLAUDE_CODE_SESSION_ATTENDED=0) never passes, so its record has no `replies`.
"""
import glob
import json
import os
import re
import sys
import tempfile
import time

WAITS = {"subagent", "shell", "workflow", "cloud session"}
SID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
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


def write_record(d: dict, sid: str, types: list, tasks) -> None:
    stops = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude", "stops")
    os.makedirs(stops, exist_ok=True)
    path = os.path.join(stops, sid + ".json")
    now = time.time()
    rec = {"session_id": sid, "time": now, "waits": [t for t in types if t in WAITS],
           "tasks": [t.get("type") if isinstance(t, dict) and isinstance(t.get("type"), str)
                     and t.get("type") else "unlabeled"
                     for t in (tasks if isinstance(tasks, list) else [])]}
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
    tasks = d.get("background_tasks")
    types = [t.get("type") for t in tasks if isinstance(t, dict)] if isinstance(tasks, list) else []
    busy = 1 if any(t in WAITS for t in types) else 0
    sid = d.get("session_id")
    if not spawned and isinstance(sid, str) and SID.fullmatch(sid):
        try:
            write_record(d, sid, types, tasks)
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
