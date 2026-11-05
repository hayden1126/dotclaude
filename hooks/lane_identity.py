"""SessionStart/Stop/SessionEnd hook for lanes; hooks/lane-identity.sh runs it.

SessionStart (every source: startup, resume, clear, compact, fork):
  in a lane     tells the model its absolute identity (lane id, what its worktree has checked
                out: a branch, or a detached HEAD's commit; lane.json's branch, labeled, when
                HEAD can't be read; claims, ports and the lane's live serves, record path)
                and the rules that keep it absolute, and appends {session_id, startedAt} to
                lane.json sessions[] (not again for a session already listed and not ended, so a
                compact keeps its start). On compact it adds "re-read your record": the summary
                holds the feel, the record the facts.
  in main       one board line when the repo has lanes, from the records alone (no git or gh),
                then the lead heal (below), which prints nothing.
  otherwise     silent: a repo with no lanes is unchanged.
Stop, SessionEnd (in a lane):
  copies <lane>/.lane/ to <common-dir>/lanes/<id>/mirror/, so a raw `git worktree remove` (which
  deletes ignored files) loses nothing. SessionEnd also stamps endedAt and the reason on the
  session's entry, which `lane ls` uses for its handoff? flag.
SessionStart and Stop (in main): the lead heal. When lanelib.lead_relink proves this session
  continues the recorded lead (a resume, a /clear or a /pass successor), it runs the sibling
  `lane lead --expect-sid <id>`, which applies every lead check to that very session and
  rewrites the record, so `lane addr lead` and the tab bar follow. Nearly every call costs one
  read and one stat, and a refusal is retried on the next Stop.

Subagent payloads (agent_id) are skipped. Writes take the lanes lock with a short timeout. Any
failure is logged to $XDG_STATE_HOME/dotclaude/lane-identity.log and stays silent (fail open).
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "skills",
                       "lanes", "scripts")
sys.path.insert(0, SCRIPTS)
import lanelib  # noqa: E402

def started() -> float:
    """This process's start on time.monotonic()'s clock, from /proc/self/stat (field 22, clock
    ticks since boot, against CLOCK_BOOTTIME): interpreter start and imports count against the
    5 s kill too. Now, if it can't be read."""
    now = time.monotonic()
    try:
        with open("/proc/self/stat") as f:
            ticks = int(f.read().rpartition(")")[2].split()[19])
        return now - max(0.0, time.clock_gettime(time.CLOCK_BOOTTIME)
                         - ticks / os.sysconf("SC_CLK_TCK"))
    except (OSError, ValueError, IndexError, AttributeError):
        return now


T0 = started()  # the hook's start, for the serves part's deadline
LOCK_WAIT = 2.0
# Each git call that reads HEAD. settings.json kills the hook at 5 s, which costs the whole line,
# so the lock wait and two calls (a detached HEAD makes two) must time out well before that.
# resolve()'s git keeps lanelib's 60 s: one that hangs there leaves no lane to name anyway, and
# a slow one under load still finishes inside the 5 s.
GIT_WAIT = 1.0
SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
MAX_SESSIONS = 50
# The `lane lead` a proven relink runs: it gives up a second ahead of the hook's 5 s, leaving
# room for resolve() and the proof.
RELINK_WAIT = 3.0


def log(line):
    try:
        d = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "lane-identity.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def checked_out(repo: lanelib.Repo, lane: dict) -> str:
    """What the worktree has checked out, for the identity line: lane.json's branch is stale once
    the lane runs `git switch` for a follow-up PR. `lane_head` in the lane CLI names the same
    thing from `git worktree list`; the hook doesn't import the CLI, so it asks git here. The
    admin dir is sandbox-writable, so only a valid_branch name or a hex commit reaches the
    context; anything else names lane.json's branch and says so."""
    def fallback(why):
        log(f"head unreadable lane={lane['id']}: {why}")
        return f"branch `{lane['branch']}` (lane.json's: the worktree's HEAD couldn't be read)"

    try:
        p = lanelib.git(["symbolic-ref", "-q", "HEAD"], repo.toplevel, timeout=GIT_WAIT)
        if p.returncode == 1:  # detached
            p = lanelib.git(["rev-parse", "--verify", "-q", "HEAD"], repo.toplevel,
                            timeout=GIT_WAIT)
            sha = p.stdout.strip()
            if p.returncode == 0 and SHA_RE.fullmatch(sha):
                return f"a detached HEAD at `{sha[:12]}`"
            return fallback(f"rev-parse exit {p.returncode}")
    except (OSError, ValueError, subprocess.SubprocessError) as e:  # ValueError: not UTF-8
        return fallback(f"{type(e).__name__}: {e}")
    ref = p.stdout.strip()
    name = ref.removeprefix("refs/heads/")
    if p.returncode != 0 or name == ref or not lanelib.valid_branch(name):
        return fallback(f"symbolic-ref exit {p.returncode}, {ref[:80]!r}")
    return f"branch `{name}`"


SERVE_CAP = 60  # characters of each live serve's command the line names
# The serves part runs last, after resolve()'s git, the lock wait and checked_out's git, and gets
# at most SERVE_BUDGET, never past SERVES_BY seconds from this process's start (T0): the 5 s kill
# costs the whole line, and bash's start before it and the print after need the rest. When the
# steps before it took that long, the serves part is skipped.
SERVE_BUDGET = 1.0
SERVES_BY = 4.0


def live_serves(repo: lanelib.Repo, lane: dict, deadline: float) -> str:
    """' (serves: 5191 npm run dev; 5192 vite, not listening)' for the lane's serves that still
    run in its dir (lanelib.serve_state), from serve's own records (a dir only sandbox-off serve
    writes), or '': a record that won't read, from an earlier boot or with nothing left running
    there names nothing. It raises TimeoutError past deadline (time.monotonic), and the caller
    drops only this part."""
    parts = []
    for rec in lanelib.served_records(repo, lane["id"]):
        state = lanelib.serve_state(rec, lane["path"], deadline)
        if state is not None:
            parts.append(f"{rec['port']} {lanelib.serve_text(rec, SERVE_CAP)}"
                         f"{'' if state == 'listening' else ', not listening'}")
    return f" (serves: {'; '.join(parts)})" if parts else ""


def lane_context(lane: dict, source: str, where: str, serving: str = "") -> str:
    claims = ", ".join(lane.get("claims", [])) or "none"
    lines = [
        f"You are lane `{lane['id']}`: {where}, claims {claims}, "
        f"{lanelib.ports_text(lane)}{serving}. Your record is {lanelib.record_path(lane)} "
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
    The caller holds the lanes lock. Nothing changed since the last copy (the stamp) means no
    copy, so a Stop on every turn stays cheap.

    This runs unsandboxed after every turn, and the lane's sandbox can write both sides (its
    record, and the common dir): every removal, rename and write goes by name under lanes/<id>,
    opened from the main checkout with O_NOFOLLOW (lanelib.common_fd), and lanelib.copy_record
    opens each name by fd, so a link swapped in anywhere is never followed."""
    lanelib.mirror_dir(repo, lane["id"], restore=True)
    src = lanelib.record_dir(lane)
    if lanelib.record_is_link(lane):
        log(f"mirror refused lane={lane['id']}: {src} is a symlink, not a record dir")
        return
    if not os.path.isdir(src):
        return
    changed = lanelib.newest_mtime(src)
    fd = lanelib.common_fd(repo, f"{lanelib.LANES}/{lane['id']}")
    try:
        try:
            stamp = os.open("mirror.stamp", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            try:
                if (stat.S_ISREG(os.fstat(stamp).st_mode) and lanelib.real_dir_at(fd, "mirror")
                        and changed <= float(os.read(stamp, 64))):
                    return
            finally:
                os.close(stamp)
        except (OSError, ValueError):
            pass
        shutil.rmtree("mirror.new", dir_fd=fd, ignore_errors=True)
        try:
            os.mkdir("mirror.new", dir_fd=fd)
            new = os.open("mirror.new", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            try:
                # Walked from / at the lane's real path: lane.json's is the lane's to write.
                real = os.path.realpath(lane["path"])
                rec = lanelib.open_dir("/", f"{real}/{lanelib.RECORD_DIR}")
                try:
                    lanelib.copy_record(rec, new)
                finally:
                    os.close(rec)
            finally:
                os.close(new)
        except BaseException:
            shutil.rmtree("mirror.new", dir_fd=fd, ignore_errors=True)
            raise
        shutil.rmtree("mirror.old", dir_fd=fd, ignore_errors=True)
        try:
            if lanelib.real_dir_at(fd, "mirror"):
                os.rename("mirror", "mirror.old", src_dir_fd=fd, dst_dir_fd=fd)
            os.rename("mirror.new", "mirror", src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:  # a mirror planted as a link, say: mirror.old stays to restore
            shutil.rmtree("mirror.new", dir_fd=fd, ignore_errors=True)
            raise
        shutil.rmtree("mirror.old", dir_fd=fd, ignore_errors=True)
        lanelib.write_at(fd, "mirror.stamp", repr(changed))
    finally:
        os.close(fd)


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
        except OSError as e:  # mirror removed its own mirror.new
            log(f"mirror skipped lane={lane['id']} {type(e).__name__}: {e}")


def relink(repo: lanelib.Repo, event: dict) -> None:
    """The lead heal: on proof (lanelib.lead_relink) that this session continues the recorded
    lead, run this checkout's own `lane lead` from the session's cwd, expecting the proved id.
    It applies every lead check (interactive, a socket, the main checkout, no linked worktree,
    no lane's session above) and writes the record atomically; until the session file or
    socket exists it refuses, and the next Stop tries again. One log line per attempt; never
    any output."""
    sid = event.get("session_id")
    if not isinstance(sid, str) or not lanelib.SID.fullmatch(sid):
        return
    why = lanelib.lead_relink(repo, sid)
    if why is None:
        return
    try:
        # --expect-sid: `lane lead` records only the session the proof was about.
        p = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "lane"), "lead",
                            "--expect-sid", sid], cwd=event["cwd"], stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, timeout=RELINK_WAIT)
    except subprocess.TimeoutExpired:
        log(f"relink {why} sid={sid} timed out after {RELINK_WAIT:g} s")
        return
    said = (p.stdout.strip() or p.stderr.strip()).partition("\n")[0]
    log(f"relink {why} sid={sid} rc={p.returncode}: {said[:300]}")


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
            where = checked_out(repo, lane)
            try:
                serving = live_serves(repo, lane, min(time.monotonic() + SERVE_BUDGET,
                                                      T0 + SERVES_BY))
            except Exception as e:  # the identity line matters more than the serves
                log(f"serves skipped {type(e).__name__}: {e}")
                serving = ""
            text = lane_context(lane, event.get("source") or "", where, serving)
        elif kind == "main" and lanes:
            text = board_line(repo, lanes)
        else:
            text = None
        if text is not None:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                                     "additionalContext": text}}), flush=True)
    elif name in ("Stop", "SessionEnd") and kind == "lane":
        end(repo, lane, event)
    if kind == "main" and name in ("SessionStart", "Stop"):
        try:  # after the board line, so nothing here can cost it
            relink(repo, event)
        except Exception as e:  # fail open, as main's caller does, but say where
            log(f"relink error {type(e).__name__}: {e}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a broken hook must never break a session
        log(f"error {type(e).__name__}: {e}")
