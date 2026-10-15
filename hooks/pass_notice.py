"""pass-notice: tell a session, once, that the /pass it queued was dropped.

skills/pass/scripts/pass-respawn's waiter respawns or compacts the session's tmux pane once its
turn ends. When it drops the pass instead, it writes $XDG_STATE_HOME/dotclaude/pass-notice/
<session>.json (atomically, mode 0600): {"v": 1, "session_id", "outcome", "mode", "called",
"dropped", "text"}. Before this hook only tmux heard about a drop, so a session went on saying
"the pass is still queued" long after it dropped.

hooks/pass-notice.sh runs this file with python3 -I on UserPromptSubmit (a typed prompt, an
agent's hand-back or a task notice) and on a main-thread PostToolUse, passing the event on
stdin, and only when the session's notice is there (or the shim found no plain session id in
the payload: this file parses it for real). The first such event of the session claims the
notice by renaming it to <session>.json.<pid>.taken (a FileNotFoundError means another hook took
it: say nothing), reads it, deletes it, and gives its text to the model as
hookSpecificOutput.additionalContext. So each notice is said exactly once.

It is said only when it is a JSON object with v == 1 (an int), the payload's session_id and a
non-blank str text, cut to CAP characters. Anything else is deleted unsaid, with a line to stderr
(the shim appends it to pass-notice.err) that never quotes the notice. The file is opened with
O_NOFOLLOW (a symlink is deleted unread, its target untouched) and read only as a regular file
of at most MAX_BYTES, in UTF-8. Sandbox-off code writes it into a dir the Bash sandbox can't
write, but the text is still untrusted: it only ever becomes model context, never runs.

Skipped, leaving the notice for a later event: a subagent's event (any agent_id), every other
event, and a session id that isn't a plain name (stop_ring.SID). Prints at most one JSON object
and fails open. Stdlib only; keep the source ASCII. Tests: tests/setup/test_pass_notice.py.
"""
import json
import os
import stat
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import autopass_state as aps  # noqa: E402
import stop_ring  # noqa: E402

EVENTS = ("UserPromptSubmit", "PostToolUse")
VERSION = 1
MAX_BYTES = 64 * 1024  # a notice is well under 8 KiB; a bigger file is dropped unread
CAP = 4000             # characters of text said at most


def notice_path(sid: str) -> str:
    return os.path.join(aps.state_dir(), "pass-notice", sid + ".json")


def log(sid, why: str) -> None:
    sys.stderr.write("%s pass-notice %s: %s\n" % (time.strftime("%F %T"), sid, why))


def read_notice(path: str):
    """The JSON value in the file at path. Raises OSError for a symlink (O_NOFOLLOW), ValueError
    for a file that isn't regular (O_NONBLOCK, so a FIFO doesn't hang the open), is over
    MAX_BYTES, isn't UTF-8 or isn't JSON, and RecursionError for too deep a nesting."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise ValueError("not a regular file")
        data = f.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("over %d bytes" % MAX_BYTES)
    return json.loads(data.decode("utf-8"))


def problem(notice, sid: str):
    """Why the notice can't be said to session sid, or None when it can."""
    if not isinstance(notice, dict):
        return "not a JSON object"
    if not aps.is_int(notice.get("v")) or notice["v"] != VERSION:
        return "not version %d" % VERSION
    if notice.get("session_id") != sid:
        return "another session's id inside"
    text = notice.get("text")
    if not isinstance(text, str) or not text.strip():
        return "no text"
    return None


def claim(sid: str):
    """The text of the session's notice, cut to CAP, or None. Whoever renames the notice owns
    it, so at most one hook says it; the claimed file is deleted whatever it holds."""
    path = notice_path(sid)
    taken = "%s.%d.taken" % (path, os.getpid())
    try:
        os.rename(path, taken)  # moves a symlink itself, never its target
    except FileNotFoundError:
        return None             # no notice, or another hook claimed it
    try:
        try:
            notice = read_notice(taken)
        except (OSError, ValueError, RecursionError) as e:
            log(sid, "dropped an unreadable notice (%s: %.200s)" % (type(e).__name__, e))
            return None
        why = problem(notice, sid)
        if why:
            log(sid, "dropped a notice: " + why)
            return None
        return notice["text"][:CAP]
    finally:
        try:
            os.unlink(taken)
        except OSError:
            pass


def handle(d: dict):
    """The output object for event d, or None."""
    event, sid = d.get("hook_event_name"), d.get("session_id")
    if event not in EVENTS or "agent_id" in d or not isinstance(sid, str) \
            or not stop_ring.SID.fullmatch(sid):
        return None
    text = claim(sid)
    if text is None:
        return None
    return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}}


def main() -> None:
    try:
        d = json.load(sys.stdin.buffer)
        out = handle(d) if isinstance(d, dict) else None
    except Exception as e:  # fail open: say nothing to the session
        sys.stderr.write("%s pass-notice: %s: %.200s\n" % (time.strftime("%F %T"),
                                                          type(e).__name__, e))
        return
    if out:
        sys.stdout.write(json.dumps(out))
        sys.stdout.flush()


if __name__ == "__main__":
    main()
