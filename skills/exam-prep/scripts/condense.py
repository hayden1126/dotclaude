#!/usr/bin/env python3
"""Condense Claude Code session transcripts into private shards for the retro (12-retro step 2).

  condense.py [--since TIME] [--until TIME] OUT_DIR TRANSCRIPT.jsonl...

Each transcript (one JSON record per line) becomes OUT_DIR/<the first 8 characters of its file name,
up to its first dot>.md. The shard opens with its transcript's file name, the session's working
directory and its earliest and latest timestamps, then keeps, in order, each with its timestamp to
the second, in UTC:
- the student's typed turns in full, up to 6000 characters each, as `### [<time>] STUDENT`
  blocks; a slash command as one `STUDENT COMMAND:` line and a `!` shell command as one
  `STUDENT BASH:` line, each up to 6000 characters; an interrupt as `INTERRUPTED`;
- a message the student typed while the session was working (Claude Code queues it), as a
  `### [<time>] STUDENT (sent mid-turn)` block, up to 6000 characters;
- the student's answers to a question dialog, as `### [<time>] STUDENT ANSWER` blocks (each
  question with its answer and any note), and a tool call they rejected as a `STUDENT REJECTED
  <tool>` line, followed by what they said about it, when anything, as a `STUDENT` block;
- the assistant's text cut to 400 characters, as `CLAUDE:` lines;
- one `tool <Name>: <its first telling argument, cut to 160>` line per tool call (a question
  dialog's questions, cut to 400);
- each other failed tool result cut to 300 characters, as `TOOL ERROR:` lines.
Every line kind is one line: its newlines become spaces. What Claude Code puts into a user turn
itself is dropped: a record marked `isMeta` (a skill's body, a peer session's message, a subagent's
hand-back) or by a non-human `origin`, and, in a turn not marked as typed (`origin.kind` "human"),
each text block that opens with an injected wrapper (a system reminder, a task notification, hook
output), and in any turn each block of a command's output (a `!` command's, a local command's) or of
IDE context.
So are subagent (sidechain) records and compaction summaries. A shard is what the student typed
and what the session did.

--since and --until (ISO 8601 times with a UTC offset, as `git log --format=%cI` and `date
-Iseconds` print them; a trailing `Z` too) keep only the records stamped at or after --since and
before --until, so two windows that meet neither drop nor repeat a record. They go before OUT_DIR.
A record with no timestamp is then dropped, and a tool result in the window still names a call made
before it. A transcript with no record in the window makes no shard: the script prints `<name>
outside the window` and removes an older shard of that name. A timestamp it can't read is counted
on stderr and its record dropped, with exit 1; when nothing else is in the window, the older shard
is kept.

A shard holds the student's words verbatim, so OUT_DIR must stay private: the script refuses an
OUT_DIR inside a git work tree (the skill's checkout, or a hub, its symlinks resolved), and two
transcripts whose shard names would collide. It sets OUT_DIR to mode 0700 and writes each shard to a
new 0600 file it then renames into place, so a link planted at a shard's path is replaced, never
written through, and a failed write leaves an older shard whole. A shard of the same name already in
OUT_DIR is replaced, so a rerun refreshes it. It prints one line per shard, its name and size, never
its text. A line that isn't a JSON record is skipped. Exit 0; 1 when a transcript can't be read, a
shard can't be written (the others are still written) or a timestamp can't be read in a window; 2
on bad usage (a time with no offset, --since not before --until, an option after OUT_DIR), a
refused or unusable OUT_DIR, or colliding names. Stdlib only."""
import json
import os
import sys
from datetime import datetime, timezone

USER_CAP = 6000
ASSISTANT_CAP = 400
ERROR_CAP = 300
HINT_CAP = 160
OUTPUT = ("<bash-stdout>", "<bash-stderr>", "<local-command-stdout>", "<local-command-caveat>")
NEVER_TYPED = OUTPUT + ("<ide_opened_file>", "<ide_selection>")
INJECTED = NEVER_TYPED + ("<system-reminder>", "<task-notification>", "<cross-session-message",
                          "<agent-message", "<user-prompt-submit-hook>",
                          "Another Claude session sent a message:")
COMMAND = ("<command-name>", "<command-message>")
SAID = "the user said:"
REFUSED = "The user doesn't want to proceed with this tool use"
HINT_KEYS = ("file_path", "path", "command", "pattern", "url", "description", "skill", "prompt")


def moment(stamp):
    """An ISO 8601 time with a UTC offset, as an aware datetime in UTC; None for anything else,
    a time UTC can't hold included. A
    trailing `Z`, which Claude Code writes, is read as `+00:00`: Python reads it only from 3.11."""
    s = str(stamp)
    if s[-1:] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        t = datetime.fromisoformat(s)
        return t.astimezone(timezone.utc) if t.tzinfo else None
    except (ValueError, OverflowError):
        return None


def blocks_of(content):
    """The text blocks of a message's content."""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    return [str(b.get("text", "")) for b in content
            if isinstance(b, dict) and b.get("type") == "text"]


def text_of(content):
    return "\n".join(blocks_of(content))


def clip(s, n):
    s = str(s).strip()
    return s if len(s) <= n else s[:n] + f" [...{len(s) - n} more chars]"


def flat(s):
    return str(s).replace("\r", " ").replace("\n", " ")


def line(ts, label, text, cap):
    return f"[{ts}] {label}: {clip(flat(text), cap)}"


def tool_line(block):
    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
    if block.get("name") == "AskUserQuestion" and isinstance(inp.get("questions"), list):
        asked = " / ".join(str(q.get("question", "")) for q in inp["questions"]
                           if isinstance(q, dict))
        return f"tool AskUserQuestion: {clip(flat(asked), ASSISTANT_CAP)}"
    hint = next((str(inp[k]) for k in HINT_KEYS if k in inp), "")
    return f"tool {block.get('name')}: {clip(flat(hint), HINT_CAP)}"


def answers_of(rec, block):
    """A question dialog's answers: each question with its answer and any note the student added."""
    result = rec.get("toolUseResult")
    if isinstance(result, dict) and isinstance(result.get("answers"), dict):
        notes = result.get("annotations") if isinstance(result.get("annotations"), dict) else {}
        out = []
        for q, a in result["answers"].items():
            out.append(f"{q} -> {a}")
            note = notes.get(q)
            if isinstance(note, dict) and note.get("notes"):
                out.append(f"  note: {note['notes']}")
        return "\n".join(out)
    return text_of(block.get("content"))


def results(rec, content, ts, tools):
    """The shard's lines for the tool results in one user record."""
    out = []
    for b in content if isinstance(content, list) else []:
        if not (isinstance(b, dict) and b.get("type") == "tool_result"):
            continue
        tool = tools.get(str(b.get("tool_use_id")), "a tool")
        said = text_of(b.get("content"))
        if b.get("is_error") and (rec.get("toolDenialKind") == "user-rejected"
                                  or said.lstrip().startswith(REFUSED)):
            out.append(f"[{ts}] STUDENT REJECTED {tool}")
            at = said.find(SAID)
            if at >= 0 and said[at + len(SAID):].strip():
                out += ["", f"### [{ts}] STUDENT", clip(said[at + len(SAID):], USER_CAP), ""]
        elif b.get("is_error"):
            out.append(line(ts, "TOOL ERROR", said, ERROR_CAP))
        elif tool == "AskUserQuestion":
            out += ["", f"### [{ts}] STUDENT ANSWER", clip(answers_of(rec, b), USER_CAP), ""]
    return out


def queued(rec, ts):
    """A message the student typed mid-turn, which Claude Code keeps as an attachment record."""
    a = rec.get("attachment") if isinstance(rec.get("attachment"), dict) else {}
    prompt = a.get("prompt")
    if a.get("type") != "queued_command" or not isinstance(prompt, str) or not prompt.strip():
        return []
    origin = a.get("origin") if isinstance(a.get("origin"), dict) else None
    if origin is not None and origin.get("kind") != "human":
        return []
    if origin is None and (a.get("isMeta") or prompt.strip().startswith(INJECTED)):
        return []
    return ["", f"### [{ts}] STUDENT (sent mid-turn)", clip(prompt, USER_CAP), ""]


def condense(path, since=None, until=None):
    """The shard's text for one transcript, None when a window is given and none of its records
    falls inside it; and how many timestamps the window couldn't read."""
    body, cwd, first, last, tools, unread = [], None, None, None, {}, 0
    windowed = since is not None or until is not None
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                rec = json.loads(raw)
            except (ValueError, RecursionError):
                continue
            if not isinstance(rec, dict) or rec.get("isSidechain") or rec.get("isCompactSummary"):
                continue
            cwd = cwd or rec.get("cwd")
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            content = msg.get("content")
            if rec.get("type") == "assistant" and isinstance(content, list):
                tools.update((str(b.get("id")), str(b.get("name"))) for b in content
                             if isinstance(b, dict) and b.get("type") == "tool_use")
            t = moment(rec.get("timestamp"))
            if windowed:
                if t is None:
                    unread += rec.get("timestamp") not in (None, "")
                    continue
                if (since is not None and t < since) or (until is not None and t >= until):
                    continue
            if t is not None:
                ts = t.strftime("%Y-%m-%dT%H:%M:%S")
            else:
                ts = str(rec.get("timestamp") or "")[:19]
            if ts:
                first, last = min(first or ts, ts), max(last or ts, ts)
            if rec.get("type") == "attachment":
                body += queued(rec, ts)
            elif rec.get("type") == "user":
                body += results(rec, content, ts, tools)
                origin = rec.get("origin") if isinstance(rec.get("origin"), dict) else None
                if rec.get("isMeta") or (origin is not None and origin.get("kind") != "human"):
                    continue
                typed = origin is not None or rec.get("promptSource") == "typed"
                dropped = NEVER_TYPED if typed else INJECTED
                text = "\n".join(x.strip() for x in blocks_of(content)
                                 if x.strip() and not x.strip().startswith(dropped))
                if not text:
                    continue
                if text.startswith(COMMAND):
                    body.append(line(ts, "STUDENT COMMAND", text, USER_CAP))
                elif text.startswith("<bash-input>"):
                    body.append(line(ts, "STUDENT BASH", text, USER_CAP))
                elif text.startswith("[Request interrupted"):
                    body.append(f"[{ts}] INTERRUPTED")
                else:
                    body += ["", f"### [{ts}] STUDENT", clip(text, USER_CAP), ""]
            elif rec.get("type") == "assistant" and isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and str(b.get("text", "")).strip():
                        body.append(line(ts, "CLAUDE", b["text"], ASSISTANT_CAP))
                    elif b.get("type") == "tool_use":
                        body.append(f"[{ts}] {tool_line(b)}")
    if windowed and first is None:
        return None, unread
    head = [f"# Shard of {os.path.basename(path)}", "",
            f"- Working directory: {cwd or 'not recorded'}",
            f"- From {first or 'not recorded'} to {last or 'not recorded'} (UTC)", ""]
    return "\n".join(head + body) + "\n", unread


def in_work_tree(path):
    """True when path, or the nearest existing directory above it, is inside a git work tree."""
    d = os.path.realpath(path)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def write_private(path, text):
    """Write text to a new 0600 file beside path, then rename it over path: a link planted at
    path is replaced, never written through, and a failed write leaves path as it was."""
    tmp = os.path.join(os.path.dirname(path), f".{os.path.basename(path)}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with open(fd, "w", encoding="utf-8", errors="replace") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    window = {"--since": None, "--until": None}
    while len(args) >= 2 and args[0] in window:
        window[args[0]] = moment(args[1])
        if window[args[0]] is None:
            print(f"condense: {args[0]} {args[1]}: not an ISO 8601 time with a UTC offset",
                  file=sys.stderr)
            return 2
        args = args[2:]
    since, until = window["--since"], window["--until"]
    if since is not None and until is not None and since >= until:
        print("condense: --since must come before --until", file=sys.stderr)
        return 2
    if len(args) < 2 or args[0] == "-h" or any(a.startswith("--") for a in args):
        print(__doc__.split("\n\n")[1], file=sys.stderr)
        return 2
    out_dir, transcripts = args[0], args[1:]
    if in_work_tree(out_dir):
        print(f"condense: {out_dir} is inside a git work tree; shards quote the student, so they "
              f"go to a private directory", file=sys.stderr)
        return 2
    names = {}
    for p in transcripts:
        name = os.path.basename(p).split(".")[0][:8] + ".md"
        if name in names:
            print(f"condense: {p} and {names[name]} both make {name}", file=sys.stderr)
            return 2
        names[name] = p
    try:
        os.makedirs(out_dir, mode=0o700, exist_ok=True)
        os.chmod(out_dir, 0o700)
    except OSError as e:
        print(f"condense: {out_dir}: {e.strerror}", file=sys.stderr)
        return 2
    status = 0
    for name, p in names.items():
        path = os.path.join(out_dir, name)
        try:
            shard, unread = condense(p, since, until)
            if unread:
                print(f"condense: {p}: {unread} timestamps it can't read, their records dropped",
                      file=sys.stderr)
                status = 1
            if shard is None and unread:
                continue
            if shard is None:
                if os.path.lexists(path):
                    os.unlink(path)
                print(f"{name} outside the window")
                continue
            write_private(path, shard)
        except OSError as e:
            print(f"condense: {p} -> {name}: {e.strerror}", file=sys.stderr)
            status = 1
            continue
        print(f"{name} {len(shard.encode('utf-8', 'replace')) // 1024}K")
    return status


if __name__ == "__main__":
    sys.exit(main())
