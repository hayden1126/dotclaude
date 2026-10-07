"""PreToolUse(Bash) guard for deletes that run outside the sandbox; hooks/delete-guard.sh runs it.

Inside the sandbox a delete can only reach the working directory and $TMPDIR. A command run with
dangerouslyDisableSandbox can reach everything, and its variables can mean something else:
$TMPDIR is set only inside the sandbox, so out there `rm -rf "$TMPDIR"/x` aims at /tmp/x
(2026-10-06). So, for a sandbox-off command only, a delete (rm, rmdir, shred, unlink, or find
with -delete or -exec rm) is denied when one of its paths

  - uses a variable the command didn't set before the delete (`X=...`, `export X=`, `for X in`,
    `read X`), other than HOME, USER and PWD, which are the same everywhere; a command
    substitution counts as unset too, since it can come back empty;
  - is, after the command's own literal assignments and ~, a catastrophic target: /, a top-level
    system directory, the home directory or one of its main trees (~/.claude, ~/code, ...), or a
    glob directly inside one of those (`~/*`, `/tmp/*`).

Replayed over a month of transcripts (4339 sandbox-off Bash calls, 247 with a delete), it would
have denied 2, both real hazards. A sandboxed command is never judged, and neither is any other
command: normal rm runs without prompts. Heredoc bodies are skipped, so a script that only
mentions rm is not a delete. Not covered: `xargs rm` (its paths come from stdin), and a delete
inside `bash -c`, `eval` or a script file.

Fails open: an error or an unparsable command allows the call and is logged, as is every deny,
to $XDG_STATE_HOME/dotclaude/delete-guard.log.
"""
import json
import os
import re
import shlex
import sys
import time

DELETERS = {"rm", "rmdir", "shred", "unlink"}
# Words that can precede the command itself: wrappers and the shell keywords that open a body.
WRAPPERS = {"sudo", "command", "nohup", "time", "env", "builtin", "exec",
            "do", "then", "else", "elif", "if", "while", "until", "!", "{"}
STABLE = {"HOME", "USER", "PWD"}
SEPARATORS = {";", "&&", "||", "|", "&", "(", ")", "\n", ";;", "|&"}
VAR = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def log(line):
    try:
        d = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "delete-guard.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


def strip_heredocs(command):
    """Drop heredoc bodies: their text is data for another program, not shell words."""
    out, lines, i = [], command.split("\n"), 0
    while i < len(lines):
        out.append(lines[i])
        ends = [m.group(2) for m in HEREDOC.finditer(lines[i])]
        i += 1
        for end in ends:
            while i < len(lines) and lines[i].strip() != end:
                i += 1
            i += 1
    return "\n".join(out)


def segments(command):
    """Simple commands as word lists, split at ; && || | & ( ) and newlines."""
    lex = shlex.shlex(strip_heredocs(command).replace("$(", "$( "), posix=True,
                      punctuation_chars=";&|()")
    lex.whitespace = " \t\r"
    lex.wordchars += "$-./~*?[]{}=:+@%,^!#"
    lex.commenters = ""
    seg = []
    for tok in lex:
        if tok in SEPARATORS or set(tok) <= set(";&|()") or tok == "\n":
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
    if seg:
        yield seg


def catastrophic():
    home = os.path.expanduser("~")
    tops = {"/", "/tmp", "/var", "/usr", "/etc", "/opt", "/bin", "/lib", "/boot", "/root",
            "/home", "/mnt", "/mnt/c", "/mnt/c/Users", "/srv", "/proc", "/sys", "/dev"}
    trees = {home} | {os.path.join(home, d) for d in (
        ".claude", ".config", ".local", ".local/share", ".local/state", ".ssh", "code", "dotclaude",
        "scratch", "vault", ".codex", ".cache")}
    return tops | trees


def judge(command):
    """None to allow, or (reason, note) to deny."""
    assigned = {}
    for words in segments(command):
        i = 0
        while i < len(words) and (ASSIGN.match(words[i]) or words[i] in WRAPPERS):
            m = ASSIGN.match(words[i])
            if m:
                assigned[m.group(1)] = m.group(2)
            i += 1
        if i >= len(words):
            continue
        name, args = os.path.basename(words[i]), words[i + 1:]
        if name in ("export", "local", "declare", "readonly", "typeset"):
            for a in args:
                m = ASSIGN.match(a)
                if m:
                    assigned[m.group(1)] = m.group(2)
            continue
        if name == "for" and args:
            assigned[args[0]] = None
            continue
        if name in ("read", "mapfile", "readarray"):
            for a in args:
                if re.fullmatch(r"[A-Za-z_]\w*", a):
                    assigned[a] = None
            continue
        if name in DELETERS:
            paths = [a for a in args if not a.startswith("-")]
        elif name == "find" and ("-delete" in args or "rm" in args):
            paths = []
            for a in args:
                if a.startswith(("-", "(", "!")):
                    break
                paths.append(a)
        else:
            continue
        verdict = check(name, paths, assigned)
        if verdict:
            return verdict
    return None


def check(name, paths, assigned):
    for p in paths:
        if "$(" in p or "`" in p:
            return (f"delete-guard: this sandbox-off {name} deletes a path built from a command "
                    f"substitution ({p}), which can come back empty. Spell out the absolute path, "
                    "or run the delete sandboxed.", f"deny substitution {name} {p}")
        unset = [v for v in VAR.findall(p) if v not in assigned and v not in STABLE]
        if unset:
            v = unset[0]
            hint = " Outside the sandbox $TMPDIR is plain /tmp." if v == "TMPDIR" else ""
            return (f"delete-guard: this sandbox-off {name} deletes {p}, built from ${v}, which "
                    f"this command doesn't set; inherited variables can differ outside the sandbox "
                    f"or be empty.{hint} Spell out the absolute path, or run the delete sandboxed.",
                    f"deny unset-var ${v} {name} {p}")
        target = expand(p, assigned)
        if target is not None and is_catastrophic(target):
            return (f"delete-guard: this sandbox-off {name} would delete {p} ({target}), a "
                    "top-level or home tree. Name the specific path inside it.",
                    f"deny catastrophic {name} {target}")
    return None


def is_catastrophic(target):
    """A top-level or home tree itself, or a glob directly inside one (`~/*`, `/tmp/*`)."""
    target = os.path.normpath(target)
    if target.endswith("/*") or target == "/*":
        target = os.path.dirname(target) or "/"
    return target in catastrophic()


def expand(p, assigned):
    """The path with ~ and the command's literal assignments (or the stable variables) filled in;
    None when a value isn't known from the command text."""
    values = dict({v: os.environ.get(v) for v in STABLE}, **assigned)
    try:
        p = re.sub(r"\$\{?([A-Za-z_]\w*)\}?", lambda m: literal(values.get(m.group(1))), p)
    except LookupError:
        return None
    return os.path.expanduser(p)


def literal(value):
    if value is None or "$" in value or "`" in value:
        raise LookupError
    return value


def main():
    event = json.load(sys.stdin)
    if event.get("tool_name") != "Bash":
        return
    inp = event.get("tool_input") or {}
    if inp.get("dangerouslyDisableSandbox") is not True:
        return
    command = inp.get("command")
    if not isinstance(command, str):
        return
    try:
        verdict = judge(command)
    except ValueError as e:  # shlex: an unbalanced quote
        log(f"unparsed {type(e).__name__}: {e}: {command[:200]!r}")
        return
    if verdict:
        reason, note = verdict
        log(f"{note} session={str(event.get('session_id'))[:8]}")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a broken guard must never block a command
        log(f"error {type(e).__name__}: {e}")
