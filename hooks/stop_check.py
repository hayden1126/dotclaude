"""Stop hook for lane sessions: block a turn's end once when it ends with nothing to wait on.
hooks/stop-check.sh runs it with python3 -I; tests/setup/test_stop_check.py holds the cases.

Lane sessions went idle mid-plan (2026-11-08/09): a commit, a report, then a stop with no
question, no message and no job running, so nothing would ever wake them. This hook makes such a
stop continue once, telling the model its four ways out (continue the Next, pass, ask Hayden
through the record's Asks and a Waiting on you list, or send the lead `park me`).

The stop passes (prints nothing) when any of these holds, checked in this order:
1. It isn't a lane's main thread: a subagent's stop (a top-level agent_id), an unattended
   session (CLAUDE_CODE_SESSION_ATTENDED=0: `claude -p` or `--bg`, which no one reads), or a
   launch dir (the transcript's first cwd, not the payload's, which a Bash `cd` moves) that
   lanelib doesn't resolve to a registered lane (the main checkout, a plain dir, any error).
2. This turn was blocked already: stop_hook_active, or this hook's record names the payload's
   prompt_id (a blocked stop and the stop of the turn it continues share it). Never loops.
3. Plan mode: the session can't act until Hayden approves anyway.
4. The last reply has a line opening "Waiting on" or "Waiting for" (after any markup): a
   Waiting on you list, or `Waiting on <who>: <what>` for a wait on a lane, the lead, a person
   or a job. Lanes are taught that line at session start (hooks/lane_identity.py) and in the
   block's reason. Hayden asked for the false blocks to be tuned (2026-11-09): in the replay
   they were fair waits on someone else, which no phrase match told apart (best: 3 of 9).
5. A background task the turn waits on is running: a subagent, shell (a background Bash or a
   Monitor watch), workflow, cloud session or teammate. The Artifact tool's live watch (a
   `monitor`) and a `dream` are not waits.
6. The turn sent a message to the lead or a lane (a successful SendMessage to a `uds:` address,
   what `lane addr` prints: `park me`, `merged #N`, a question), invoked the pass skill, ran
   pass-respawn from Bash (context_watch.runs_pass_respawn: the pass skill's own step, whose
   Skill call may sit turns back), or a pass is pending (context_watch.pass_pending).
7. Hayden started the turn: its first entry with an origin is his typed prompt (origin.kind
   human), or it starts with a typed slash command, and no ExitPlanMode in the turn came back
   approved. He reads the reply before anything moves on (Hayden's pick, 2026-11-09). The
   prompts pass-respawn and `lane open` type into a pane read as human too, so a prompt opening
   "Read your lane record " or "You are lane `" is not his. A plan approved in the turn hands
   the session the whole plan, so that turn gets the test.

The turn is the transcript from the first user entry carrying the payload's prompt_id (Claude
Code stamps it on every user entry of the turn) to the end; that entry's line is found with one
byte search. When the prompt_id isn't in the transcript, the turn can't be read, so the stop
passes and a line is logged: blocking blind would miss a message or a pass.

Otherwise it blocks, records the prompt_id in $XDG_STATE_HOME/dotclaude/stop-check/<sid>.json
first, and logs one line to stop-check.log. Two blocking Stop hooks both reach the model (probe,
2.1.319, 2026-11-09), so it needs no yielding to context-watch or watch-guard. Fails open: any
error passes the stop, and its traceback goes to stderr, which the shim appends to
stop-check.err.
"""
import json
import mmap
import os
import re
import sys
import time
import traceback

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import autopass_state as aps  # noqa: E402
import context_watch  # noqa: E402

SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "lanes", "scripts")

MARKER = "[stop-check]"
WAIT_KINDS = {"subagent", "shell", "workflow", "cloud session", "teammate"}
WAITING = re.compile(r"^[\W_]*waiting (on|for)\b", re.IGNORECASE | re.MULTILINE)
MACHINE_PROMPTS = ("Read your lane record ", "You are lane `")
SLASH = "<command-message>"
PROMPT_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
SID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")

REASON = (MARKER + " This lane turn ends with nothing to wait on: no Waiting on you list, no "
          "message to the lead or a lane, no background job running, no pass. Before you stop:\n"
          "- If your record's Next or an approved plan has work left, continue it now.\n"
          "- {ctx}\n"
          "- If you need Hayden, name the decision, put it in your record's Asks for Hayden, "
          "and end your reply with a Waiting on you list.\n"
          "- If the lane is pushed and only waits its merge turn, send the lead `park me` "
          "(to what a bare `lane addr lead` prints).\n"
          "- If you wait on another lane, the lead's reply, a person or a job outside this "
          "session, end with a line `Waiting on <who>: <what>` and stop.\n"
          "- If none applies, say so in one line and stop: this check blocks once per turn.")
CTX_PAST = ("Context is {n}, past the auto-pass soft tier ({soft}): run the pass skill instead "
            "of starting new work.")
CTX_SOFT = "If context is past the auto-pass soft tier ({soft}), run the pass skill instead."
CTX_ANY = "If context is heavy (past the auto-pass soft tier), run the pass skill instead."


def state_dir() -> str:
    return os.path.join(os.environ.get("XDG_STATE_HOME")
                        or os.path.expanduser("~/.local/state"), "dotclaude")


def log(line: str) -> None:
    try:
        os.makedirs(state_dir(), exist_ok=True)
        with open(os.path.join(state_dir(), "stop-check.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def lane_of(transcript) -> str | None:
    """The id of the registered lane the session was launched in, else None (any failure
    included). The launch dir is the transcript's first recorded cwd: the payload's cwd follows
    a Bash `cd`, so a lead that cd'd into a lane would read as that lane."""
    if SCRIPTS not in sys.path:
        sys.path.insert(0, SCRIPTS)
    try:
        import lanelib
        cwd = lanelib.transcript_cwd(transcript) if isinstance(transcript, str) else None
        if not isinstance(cwd, str) or not os.path.isdir(cwd):
            return None
        repo = lanelib.resolve(cwd)
        if repo is None:
            return None
        kind, lane = repo.identity()
    except Exception:
        return None
    return lane.get("id") if kind == "lane" and isinstance(lane, dict) else None


def turn(path, prompt_id) -> list | None:
    """The turn's main-chain entries, from the first user entry carrying prompt_id to the end,
    or None when the transcript can't be read or doesn't hold it."""
    if not (isinstance(path, str) and isinstance(prompt_id, str)
            and PROMPT_ID.fullmatch(prompt_id)):
        return None
    try:
        with open(path, "rb") as f:
            if os.fstat(f.fileno()).st_size == 0:
                return None
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
                pos = m.find(b'"promptId":"' + prompt_id.encode() + b'"')
                if pos < 0:
                    return None
                tail = m[m.rfind(b"\n", 0, pos) + 1:]
    except (OSError, ValueError):
        return None
    rows = []
    for line in tail.splitlines():
        try:
            d = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if isinstance(d, dict) and not d.get("isSidechain"):
            rows.append(d)
    return rows


def blocks(entry, kind) -> list:
    """The entry's message content blocks of the given type."""
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if not isinstance(content, list):
        return []
    return [b for b in content if isinstance(b, dict) and b.get("type") == kind]


def text_of(entry) -> str:
    msg = entry.get("message")
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in blocks(entry, "text")
                   if isinstance(b.get("text"), str))


def tool_calls(rows) -> list:
    """(name, input, ok) per tool_use in the turn; ok is whether its result came back without
    is_error (False while no result is on disk)."""
    results = {}
    for d in rows:
        if d.get("type") == "user":
            for b in blocks(d, "tool_result"):
                results[b.get("tool_use_id")] = not b.get("is_error")
    calls = []
    for d in rows:
        if d.get("type") == "assistant":
            for b in blocks(d, "tool_use"):
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                calls.append((b.get("name"), inp, results.get(b.get("id"), False)))
    return calls


def hayden_started(rows, calls) -> bool:
    """Rule 7: the turn's first entry with an origin is Hayden's typed prompt (not one a tool
    typed), or the turn starts with a typed slash command, and no plan was approved in it."""
    if any(name == "ExitPlanMode" and ok for name, _, ok in calls):
        return False
    # The start: the turn's first user entry that isn't a tool result or an injected
    # reminder (isMeta with no origin). A typed slash command has no origin, and a task notice
    # later in the same turn mustn't take its place.
    start = next((d for d in rows if d.get("type") == "user" and not blocks(d, "tool_result")
                  and (isinstance(d.get("origin"), dict) or not d.get("isMeta"))), None)
    if start is None:
        return False
    text = text_of(start).lstrip()
    if isinstance(start.get("origin"), dict):
        return start["origin"].get("kind") == "human" and not text.startswith(MACHINE_PROMPTS)
    return text.startswith(SLASH)


def waiting_tasks(tasks) -> list:
    if not isinstance(tasks, list):
        return []
    return [t for t in tasks if isinstance(t, dict) and t.get("type") in WAIT_KINDS]


def ctx_line(sid, transcript) -> str:
    try:
        rec = aps.read_ctx(sid)
        win = rec.get("window")
        tiers = aps.tiers(aps.window(transcript, win if aps.is_int(win) else None))
        if not tiers:
            return CTX_ANY
        tokens = rec.get("tokens")
        if aps.is_int(tokens) and tokens >= tiers["soft"]:
            return CTX_PAST.format(n=aps.kilo(tokens), soft=aps.kilo(tiers["soft"]))
        return CTX_SOFT.format(soft=aps.kilo(tiers["soft"]))
    except Exception:
        return CTX_ANY


def record_path(sid) -> str:
    return os.path.join(state_dir(), "stop-check", sid + ".json")


def blocked_before(sid, prompt_id) -> bool:
    try:
        with open(record_path(sid)) as f:
            return json.load(f).get("prompt_id") == prompt_id
    except (OSError, ValueError, AttributeError):
        return False


def record_block(sid, prompt_id) -> None:
    d = os.path.dirname(record_path(sid))
    os.makedirs(d, exist_ok=True)
    tmp = record_path(sid) + ".%d.tmp" % os.getpid()
    with open(tmp, "w") as f:
        json.dump({"prompt_id": prompt_id, "time": time.time()}, f)
    os.replace(tmp, record_path(sid))


def explain(payload, lane, rows=None) -> tuple:
    """(the block to print or None, the rule that decided, as a short tag). lane is
    lane_of(cwd); rows, when given, are the turn's entries (the replay passes them), else they
    are read from the transcript."""
    if not isinstance(payload, dict) or payload.get("agent_id") or not lane:
        return None, "not-lane"
    sid, prompt_id = payload.get("session_id"), payload.get("prompt_id")
    if not (isinstance(sid, str) and SID.fullmatch(sid) and isinstance(prompt_id, str)):
        return None, "bad-payload"
    if payload.get("stop_hook_active") or blocked_before(sid, prompt_id):
        return None, "continued"
    if payload.get("permission_mode") == "plan":
        return None, "plan-mode"
    last = payload.get("last_assistant_message")
    if isinstance(last, str) and WAITING.search(last):
        return None, "waiting-list"
    if waiting_tasks(payload.get("background_tasks")):
        return None, "background"
    transcript = payload.get("transcript_path")
    if rows is None:
        rows = turn(transcript, prompt_id)
    if rows is None:
        log(f"pass {sid} {lane}: no turn start for prompt {prompt_id} in the transcript")
        return None, "no-turn"
    calls = tool_calls(rows)
    for name, inp, ok in calls:
        if not ok:
            continue
        if name == "SendMessage" and str(inp.get("to", "")).startswith("uds:"):
            return None, "message"
        if name == "Skill" and inp.get("skill") == "pass":
            return None, "pass-skill"
        if name == "Bash" and context_watch.runs_pass_respawn(str(inp.get("command", ""))):
            return None, "pass-skill"
    if context_watch.pass_pending(sid):
        return None, "pass-pending"
    if hayden_started(rows, calls):
        return None, "hayden"
    record_block(sid, prompt_id)
    log(f"block {sid} {lane} prompt {prompt_id}")
    return {"decision": "block", "reason": REASON.format(ctx=ctx_line(sid, transcript))}, "block"


def decide(payload, lane) -> dict | None:
    """The block to print, or None to let the stop through (explain() without the tag)."""
    return explain(payload, lane)[0]


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "0" or not isinstance(payload, dict):
            return
        out = decide(payload, lane_of(payload.get("transcript_path"))
                     if not payload.get("agent_id") else None)
        if out is not None:
            print(json.dumps(out), flush=True)
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    main()
