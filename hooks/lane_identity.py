"""SessionStart/Stop/SessionEnd hook for lanes; hooks/lane-identity.sh runs it.

SessionStart (startup, resume, clear, compact):
  in a lane     tells the model its absolute identity (lane id, branch, claims, port, record path)
                and the rules that keep it absolute, and appends {session_id, startedAt} to
                lane.json sessions[] (not again for a session already listed and not ended, so a
                compact keeps its start). On compact it adds "re-read your record": the summary
                holds the feel, the record the facts.
  in main       one board line when the repo has lanes, from the records alone (no git or gh).
  otherwise     silent: a repo with no lanes is unchanged.
Stop, SessionEnd (in a lane):
  copies <lane>/.lane/ to <common-dir>/lanes/<id>/mirror/, so a raw `git worktree remove` (which
  deletes ignored files) loses nothing. SessionEnd also stamps endedAt and the reason on the
  session's entry, which `lane ls` uses for its handoff? flag.

Subagent payloads (agent_id) are skipped. Writes take the lanes lock with a short timeout. Any
failure is logged to $XDG_STATE_HOME/dotclaude/lane-identity.log and stays silent (fail open).
"""
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                                "skills", "lanes", "scripts"))
import lanelib  # noqa: E402

LOCK_WAIT = 2.0
MAX_SESSIONS = 50


def log(line):
    try:
        d = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "lane-identity.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def lane_context(lane: dict, source: str) -> str:
    claims = ", ".join(lane.get("claims", [])) or "none"
    lines = [
        f"You are lane `{lane['id']}`: branch `{lane['branch']}`, claims {claims}, "
        f"port {lane.get('port') or 'none'}. Your record is {lanelib.record_path(lane)} "
        "(Brief, State, Decisions, Asks for Hayden, Not mine, Next): read it before acting.",
        "Other lanes' records are read-only. Ownership comes only from `lane who #<n>` (claims), "
        "never from prose, agent lists or tab titles. Never write relative identity ('another "
        "session', 'this session'): name lanes by id, requests by number, sessions by id.",
        "STATUS.md in the main checkout is project direction, not your state: your next step "
        "lives in your record.",
        "To message the lead, SendMessage to what a bare `lane addr lead` prints, run just before "
        "each send (a pass gives it a new address); never its ListAgents name or tab title, "
        "which change most turns.",
    ]
    if source == "compact":
        lines.append("Context was just compacted: re-read your record before acting.")
    return "\n".join(lines)


def board_line(repo: lanelib.Repo, lanes: list[dict]) -> str:
    parts = []
    for lane in lanes:
        claims = ",".join(lane.get("claims", []))
        stale = "" if lanelib.is_live(lane) else " stale"
        parts.append(f"{lane['id']}" + (f" ({claims})" if claims else "") + stale)
    return (f"Main checkout of a lanes repo; lanes: {'; '.join(parts)}. Board: `lane ls`; owner of "
            "a request: `lane who #<n>`. STATUS.md here is project direction; each lane's state "
            "is in its own record. To message a lane, SendMessage to what a bare `lane addr <id>` "
            "prints, run just before each send.")


def start(repo: lanelib.Repo, lane: dict, event: dict) -> None:
    sid = event.get("session_id")
    if not isinstance(sid, str) or not sid:
        return

    def append(rec):
        sessions = rec.setdefault("sessions", [])
        if any(s.get("session_id") == sid and not s.get("endedAt") for s in sessions):
            return
        sessions.append({"session_id": sid, "startedAt": lanelib.now_iso(),
                         "source": event.get("source")})
        del sessions[:-MAX_SESSIONS]

    with lanelib.lock(repo, timeout=LOCK_WAIT):
        lanelib.update_lane(repo, lane["id"], append)


def mirror(repo: lanelib.Repo, lane: dict) -> None:
    """Copy <lane>/.lane/ to lanes/<id>/mirror/, crash-safe: build mirror.new, move mirror aside
    to mirror.old, move mirror.new in, then drop mirror.old. A run killed between the moves
    leaves mirror.old as the only copy; lanelib.mirror_dir restores it before anything else.
    The caller holds the lanes lock. Links are copied as links and never followed
    (lanelib.walk_record). Nothing changed since the last copy (the stamp) means no copy, so a
    Stop on every turn stays cheap."""
    dest = os.path.join(repo.lane_dir(lane["id"]), "mirror")
    new, old, stamp = dest + ".new", dest + ".old", dest + ".stamp"
    lanelib.mirror_dir(repo, lane["id"], restore=True)
    src = lanelib.record_dir(lane)
    if lanelib.record_is_link(lane):
        log(f"mirror refused lane={lane['id']}: {src} is a symlink, not a record dir")
        return
    if not os.path.isdir(src):
        return
    changed = lanelib.newest_mtime(src)
    try:
        with open(stamp) as f:
            if os.path.isdir(dest) and changed <= float(f.read()):
                return
    except (OSError, ValueError):
        pass
    shutil.rmtree(new, ignore_errors=True)
    lanelib.copy_record(src, new)
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(dest):
        os.rename(dest, old)
    os.rename(new, dest)
    shutil.rmtree(old, ignore_errors=True)
    lanelib.write_text(stamp, repr(changed))


def end(repo: lanelib.Repo, lane: dict, event: dict) -> None:
    sid = event.get("session_id")

    def stamp(rec):
        for s in reversed(rec.setdefault("sessions", [])):
            if s.get("session_id") == sid:
                s["endedAt"] = lanelib.now_iso()
                s["reason"] = event.get("reason")
                return

    with lanelib.lock(repo, timeout=LOCK_WAIT):
        # The stamp first: a mirror killed at the hook timeout must not cost it.
        if event.get("hook_event_name") == "SessionEnd":
            lanelib.update_lane(repo, lane["id"], stamp)
        try:
            mirror(repo, lane)
        except OSError as e:  # shutil.Error is one
            log(f"mirror skipped lane={lane['id']} {type(e).__name__}: {e}")
            shutil.rmtree(os.path.join(repo.lane_dir(lane["id"]), "mirror.new"), ignore_errors=True)


def main():
    event = json.load(sys.stdin)
    if not isinstance(event, dict) or event.get("agent_id"):
        return
    cwd = event.get("cwd")
    if not isinstance(cwd, str) or not os.path.isdir(cwd):
        return
    repo = lanelib.resolve(cwd)
    if repo is None or not repo.has_lanes:
        return
    lanes = repo.lanes()
    kind, lane = repo.identity(lanes)
    name = event.get("hook_event_name")
    if name == "SessionStart":
        if kind == "lane":
            try:
                start(repo, lane, event)
            except (lanelib.LockTimeout, OSError, ValueError) as e:  # identity still matters
                log(f"register skipped {type(e).__name__}: {e}")
            text = lane_context(lane, event.get("source") or "")
        elif kind == "main" and lanes:
            text = board_line(repo, lanes)
        else:
            return
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                 "additionalContext": text}}))
    elif name in ("Stop", "SessionEnd") and kind == "lane":
        end(repo, lane, event)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a broken hook must never break a session
        log(f"error {type(e).__name__}: {e}")
