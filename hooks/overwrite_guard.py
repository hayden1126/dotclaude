"""PreToolUse(Write) guard against blind overwrites; hooks/overwrite-guard.sh runs it.

A Write over an existing, non-empty file is denied when:
  read-proof  this session's transcript holds no successful Read, Write, Edit, MultiEdit or
              NotebookEdit of the same path, no successful Bash command naming the file's path
              (a `cat`, a heredoc patch; see names_path), no @-mention of it (a `file`
              attachment) and no instructions file with its path. The Write tool's own "File has not been read
              yet" check last fired in 2.1.285 (Edit's still fires); on 2.1.289 a Write of
              `PLACEHOLDER` replaced an unread 6 KB memory file (docs/blind-overwrite-brief.md).
              A tool call this hook (or any other) denied ends in an is_error result, so it is
              no proof on a retry. The Bash rule is loose on purpose (an `ls` naming the file
              counts too): replayed over 292 real overwrites, it cut would-be denies from 34 to
              16, and the incident is still denied.
  shrink      the file is at least MIN_OLD bytes and the new content is under SHRINK of it, even
              after a Read: a stub written "to fill in later" is the incident's shape.

Accepted limit: a path is compared by where it points now, so a link retargeted after a Read
(`ln -sf`) proves its new target. A same-named Bash token in quotes (`"my notes.md copy"`) can
also prove `my notes.md`. Both need an unusual sequence, and the shrink rule still applies.

A subagent (agent_id) is judged by its own transcript, <session dir>/subagents/agent-<id>.jsonl,
since the parent's reads are not in its context. A transcript that can't be found or read skips
read-proof; the shrink rule still applies. Any other failure allows the call (fail open) and is
logged to $XDG_STATE_HOME/dotclaude/overwrite-guard.log, as is every deny.

The search maps the transcript and jumps between occurrences of the file's basename and of the
matching tool_use ids, so a 100 MB transcript costs milliseconds. Recovery after the fact is
claude-file-history (bin/): Claude Code backs up a file before each tool write.
"""
import json
import mmap
import os
import re
import stat
import sys
import time

TOOLS = {"Read", "Write", "Edit", "MultiEdit", "NotebookEdit"}
MIN_OLD = 1024
SHRINK = 0.2


def log(line):
    try:
        d = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "overwrite-guard.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def same(path, target, cwd):
    if not isinstance(path, str) or not path:
        return False
    return os.path.realpath(os.path.join(cwd, path)) == target


def lines_with(m, needle, start=0):
    """Yield (end, parsed entry) for each line of m holding needle, from start on."""
    pos = start
    while (i := m.find(needle, pos)) != -1:
        s = m.rfind(b"\n", 0, i) + 1
        e = m.find(b"\n", i)
        e = len(m) if e == -1 else e
        try:
            yield e, json.loads(m[s:e])
        except ValueError:
            pass
        pos = e + 1


def content(entry):
    msg = entry.get("message") if isinstance(entry, dict) else None
    c = msg.get("content") if isinstance(msg, dict) else None
    return [b for b in c if isinstance(b, dict)] if isinstance(c, list) else []


def proven(m, target, cwd, paths):
    """True when the transcript in m shows the file's content reached the model. paths holds the
    file's absolute paths: the one the Write gave and, through a symlink, the real one. Only lines
    holding one of their basenames are parsed (raw UTF-8: transcripts don't ASCII-escape). When
    that finds nothing, every line naming a file_path or filename is checked, which catches a
    Read through a link with yet another name; it runs only on the way to a deny."""
    names = {os.path.basename(p) for p in paths}
    names |= {n.replace(" ", "\\ ") for n in names}  # a shell-escaped space, `cat my\ notes.md`
    needles = [json.dumps(n, ensure_ascii=False)[1:-1].encode() for n in sorted(names)]
    for needle in needles + [b'"file_path"', b'"filename"']:
        for end, entry in lines_with(m, needle):
            try:
                if shown(entry, target, cwd) or any(
                        succeeded(m, t, end) for t in calls_naming(entry, target, cwd, paths)):
                    return True
            except (AttributeError, TypeError, ValueError):
                continue  # one malformed entry is no proof, and no reason to skip the rest
    return False


def shown(entry, target, cwd):
    """An attachment that put the file's content in context: an @-mention or an instructions
    file (CLAUDE.md, MEMORY.md)."""
    att = entry.get("attachment") if isinstance(entry, dict) else None
    if not isinstance(att, dict):
        return False
    if att.get("type") == "file":
        return same(att.get("filename"), target, cwd)
    return att.get("type") == "instructions" and any(
        isinstance(f, dict) and same(f.get("path"), target, cwd) for f in att.get("files") or [])


def calls_naming(entry, target, cwd, paths):
    """The ids of the entry's tool calls that read or wrote the file, or a Bash command naming it."""
    for b in content(entry):
        if b.get("type") != "tool_use" or not isinstance(b.get("id"), str):
            continue
        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
        if b.get("name") in TOOLS:
            named = same(inp.get("file_path") or inp.get("notebook_path"), target, cwd)
        else:
            named = b.get("name") == "Bash" and names_path(
                str(inp.get("command") or ""), paths, entry.get("cwd") or cwd)
        if named:
            yield b["id"]


def names_path(command, paths, cwd):
    """Whether a shell command names the file as a whole token: its absolute path, a ~/ path, or
    its path relative to the cwd the command ran in (../ included). A bare basename counts only
    for a file in that cwd, so `cat README.md` in one repo is no proof for another repo's
    README.md. A space may be backslash-escaped. A ../ form comes from the cwd's real path, since
    the shell resolves .. there. Case counts, on a Windows drive (/mnt/c) too: a mismatch costs
    one Read."""
    if not isinstance(cwd, str):
        return False
    home = os.path.expanduser("~")
    real_cwd = os.path.realpath(cwd)
    forms = set()
    for p in paths:
        forms.add(p)
        if p.startswith(home + os.sep):
            forms.add("~" + p[len(home):])
        for base in {cwd, real_cwd}:
            rel = os.path.relpath(p, base)
            if base == real_cwd or not rel.startswith(".."):
                forms.update({rel, "./" + rel})
    forms |= {f.replace(" ", "\\ ") for f in forms}
    # A path character, or an escaped space, on either side means a longer name.
    return any(re.search(r"(?<![\w./~-])(?<!\\ )" + re.escape(f) + r"(?![\w./~\\-])", command)
               for f in forms)


def succeeded(m, tool_id, start):
    for _, entry in lines_with(m, tool_id.encode(), start):
        for b in content(entry):
            if b.get("type") == "tool_result" and b.get("tool_use_id") == tool_id:
                return not b.get("is_error")
    return False


def transcript_of(event):
    path = event.get("transcript_path")
    agent = event.get("agent_id")
    if not agent:
        return path
    if event.get("agent_transcript_path"):
        return event["agent_transcript_path"]
    if not path or not path.endswith(".jsonl"):
        return None
    return os.path.join(path[:-len(".jsonl")], "subagents", f"agent-{agent}.jsonl")


def read_proof(event, target, cwd, paths):
    """True, False, or None when there is no transcript to judge by."""
    path = transcript_of(event)
    try:
        with open(path, "rb") as f:
            if os.fstat(f.fileno()).st_size == 0:
                return False
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
                return proven(m, target, cwd, paths)
    except (OSError, TypeError):  # no transcript, or no transcript_path in the event
        return None


def deny(reason, note):
    log(note)
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))


def main():
    event = json.load(sys.stdin)
    if event.get("tool_name") != "Write":
        return
    inp = event.get("tool_input") or {}
    cwd = event.get("cwd") or os.getcwd()
    raw = inp.get("file_path")
    if not isinstance(raw, str) or not raw:
        return
    target = os.path.realpath(os.path.join(cwd, raw))
    try:
        old = os.stat(target)
    except OSError:
        return
    if not stat.S_ISREG(old.st_mode) or old.st_size == 0:
        return
    who = f"session={str(event.get('session_id'))[:8]}" + (
        f" agent={event['agent_id']}" if event.get("agent_id") else "")

    paths = {os.path.abspath(os.path.join(cwd, raw)), target}
    proof = read_proof(event, target, cwd, paths)
    if proof is None:
        log(f"no-transcript {who} path={target}")
    elif not proof:
        deny(f"overwrite-guard: {raw} exists ({old.st_size} bytes) and this session has not "
             "read it, so this Write would replace content you have not seen. Read it first, "
             "or use Edit.",
             f"deny read-proof {who} size={old.st_size} path={target}")
        return

    new = len(str(inp.get("content") or "").encode())
    if old.st_size >= MIN_OLD and new < old.st_size * SHRINK:
        deny(f"overwrite-guard: this Write would shrink {raw} from {old.st_size} to {new} bytes. "
             "Use Edit to change part of it. If the shrink is intended, tell the user, then "
             "delete the file and Write it again.",
             f"deny shrink {who} old={old.st_size} new={new} path={target}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a broken guard must never block a Write
        log(f"error {type(e).__name__}: {e}")
