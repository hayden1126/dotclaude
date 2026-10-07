"""PreToolUse(Bash) guard for deletes that run outside the sandbox; hooks/delete-guard.sh runs it.

Inside the sandbox a delete can only reach the working directory and $TMPDIR. A command run with
dangerouslyDisableSandbox can reach everything, and its variables can mean something else:
$TMPDIR is the sandbox's own directory only inside the sandbox, and plain /tmp outside it, so
there `rm -rf "$TMPDIR"/x` aims at /tmp/x (2026-10-06). So, for a sandbox-off command only, a
delete (rm, rmdir, shred, unlink, or find with -delete or -exec/-execdir rm) is denied when one
of its paths

  - uses a variable the command didn't set before the delete (`X=...`, `export X=`, `for X in`,
    `read X`), a positional parameter ($1, $@), or a variable whose own value came from one
    (`D="$TMPDIR/x"; rm -rf "$D"`). HOME and USER count as set: they are the same everywhere;
  - uses a command substitution or a ${X...} expansion with an operator: either can come back
    empty or other than it reads;
  - is, after the command's own literal assignments and ~, a catastrophic target: /, a top-level
    system directory, the home directory or one of its main trees (~/.claude, ~/code, ...), or a
    glob directly inside one of those (`~/*`, `~/.*`, `/tmp/?*`).

Replayed over a month of transcripts (4346 sandbox-off Bash calls, 247 with a delete), it would
have denied 6, all a path built from $TMPDIR (directly, through a variable, or `${TMPDIR:-/tmp}`)
in a command where $TMPDIR was /tmp. A sandboxed command is never judged, and neither is any other
command: normal rm runs without prompts. A pre-pass joins backslash-newline continuations, drops
comments and replaces each $(...), `...` and $((...)) with a placeholder, outside single
quotes; heredoc bodies are skipped. Not covered: `xargs rm` (its paths come from stdin), a delete
inside `bash -c`, `eval` or a script, and quoting subtleties (a single-quoted `'$X'` is treated
as a variable, which can only over-deny).

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
KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "time"}
WRAPPERS = {"sudo", "doas", "command", "nohup", "env", "builtin", "exec", "timeout", "nice",
            "ionice", "stdbuf", "chronic"}
STABLE = {"HOME", "USER"}
SUBST = "__SUBST__"
TAINT = object()  # the value of a variable built from an unset one
EMPTYABLE = object()  # the value of a lone command substitution, which can come back empty
VAR = re.compile(r"\$(?:\{([^}]*)\}|([A-Za-z_][A-Za-z0-9_]*)|([0-9@*#?!-]))")
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
HEREDOC = re.compile(r"(?<!<)<<-?(?!<)\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


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
    """Drop heredoc bodies: their text is data for another program, not shell words. A `<<`
    inside $((...)) is a shift, and `<<<` a here-string, not a heredoc."""
    out, lines, i = [], command.split("\n"), 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        ends = [m.group(2) for m in HEREDOC.finditer(line)
                if line.count("$((", 0, m.start()) <= line.count("))", 0, m.start())]
        i += 1
        for end in ends:
            while i < len(lines) and lines[i].strip() != end:
                i += 1
            i += 1
    return "\n".join(out)


def closing(s, i, open_, close):
    """Index just past the bracket that closes the one opened before i (nesting counted; a
    bracket inside quotes, like jq's '"\\(.status)"', doesn't count)."""
    depth, quote = 1, None
    while i < len(s) and depth:
        c = s[i]
        if quote == "'":
            quote = None if c == "'" else quote
        elif c == "\\":
            i += 1
        elif c in "'\"" and quote in (None, c):
            quote = None if quote else c
        elif quote is None and c == open_:
            depth += 1
        elif quote is None and c == close:
            depth -= 1
        i += 1
    return i


def prepass(command):
    """Join continuations, drop comments, and turn substitutions into one placeholder word,
    tracking quotes so none of it happens inside single quotes."""
    s, out, i, quote = strip_heredocs(command), [], 0, None
    while i < len(s):
        c = s[i]
        if quote != "'" and c == "\\":
            if s[i + 1:i + 2] == "\n":
                i += 2
                continue
            out.append(s[i:i + 2])
            i += 2
            continue
        if quote == "'":
            quote = None if c == "'" else quote
        elif c in "'\"" and (quote is None or quote == c):
            quote = None if quote else c
        elif quote is None and c == "#" and (i == 0 or s[i - 1] in " \t\n;&|("):
            while i < len(s) and s[i] != "\n":
                i += 1
            continue
        elif s.startswith("$((", i):
            i = closing(s, i + 3, "(", ")")
            i += s[i:i + 1] == ")"
            out.append("0")
            continue
        elif s.startswith("$(", i):
            i = closing(s, i + 2, "(", ")")
            out.append(SUBST)
            continue
        elif c == "`":
            j = s.find("`", i + 1)
            i = len(s) if j == -1 else j + 1
            out.append(SUBST)
            continue
        out.append(c)
        i += 1
    return "".join(out)


def segments(command):
    """Simple commands as word lists, split at ; && || | & ( ) and newlines."""
    lex = shlex.shlex(prepass(command), posix=True, punctuation_chars=";&|()")
    lex.whitespace = " \t\r"
    lex.wordchars += "$-./~*?[]{}=:+@%,^!#"
    lex.commenters = ""
    seg = []
    for tok in lex:
        if tok == "\n" or set(tok) <= set(";&|()"):
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
    if seg:
        yield seg


def problem(text, assigned):
    """Why text can't be trusted as a path in this command, or None.

    A variable the command never set (or one built from such), a positional parameter nothing
    set, and an operator expansion are untrusted outright. A command substitution, or a variable
    holding one, may come back empty: alone that only empties the argument (`rm -rf ""` fails
    harmlessly), but with more path after it, `"$dir"/*` becomes `/*`, so that is untrusted."""
    empty = []
    for brace, name, special in VAR.findall(text):
        if special:
            if special.isdigit() or special in "@*":
                if "#positional" in assigned:
                    if assigned["#positional"] is TAINT:
                        return f"${special}, set from a variable this command doesn't set"
                    empty.append(f"${special}")
                    continue
            return f"${special}, which this command doesn't set"
        if brace:
            if not re.fullmatch(r"[A-Za-z_]\w*", brace):
                return f"${{{brace}}}, an expansion that can come back other than it reads"
            name = brace
        if name in STABLE:
            continue
        if name not in assigned:
            hint = " (outside the sandbox $TMPDIR is plain /tmp)" if name == "TMPDIR" else ""
            return f"${name}, which this command doesn't set{hint}"
        if assigned[name] is TAINT:
            return (f"${name}, whose value was built from an untrusted part (a variable this "
                    "command doesn't set, or a substitution that can come back empty)")
        if assigned[name] is EMPTYABLE:
            empty.append(f"${name}")
    empty += [SUBST] * text.count(SUBST)
    if empty and widens(text, empty):
        what = "a command substitution" if empty[0] == SUBST else f"{empty[0]}, set from one,"
        return f"{what} that can come back empty, which turns this path into {residue(text, empty)!r}"
    return None


def residue(text, empty):
    """The path as it reads if every emptyable part comes back empty."""
    for ref in sorted(set(empty), key=len, reverse=True):
        name = ref[1:]
        text = text.replace(ref, "") if ref == SUBST else \
            re.sub(r"\$(\{%s\}|%s(?![A-Za-z0-9_]))" % (re.escape(name), re.escape(name)), "", text)
    return text


def widens(text, empty):
    """Whether an empty result would aim the delete somewhere broader: an absolute or home path,
    a glob, or `.`/`..` (`"$dir"/*` becomes `/*`). A lone `"$dir"` becomes `""`, which rm
    refuses, and `$dir.txt` becomes `.txt` in the working directory."""
    rest = residue(text, empty)
    if not rest:
        return False
    first = rest.split("/")[0]
    return rest.startswith(("/", "~")) or first in (".", "..") or bool(re.search(r"[*?\[]", first))


def value_of(text, assigned):
    """What an assignment stores: TAINT if built from something untrusted, EMPTYABLE if it is a
    lone substitution (or a lone variable holding one), else its text."""
    if problem(text, assigned):
        return TAINT
    refs = [brace or name for brace, name, _ in VAR.findall(text)]
    if SUBST in text or any(assigned.get(n) is EMPTYABLE for n in refs):
        return EMPTYABLE
    return text


def command_words(words):
    """(name, args) of the segment's command after assignments, keywords and wrappers, plus the
    segment's prefix assignments; name is None for a pure assignment."""
    prefix, i = [], 0
    while i < len(words) and (ASSIGN.match(words[i]) or words[i] in KEYWORDS):
        if ASSIGN.match(words[i]):
            prefix.append(ASSIGN.match(words[i]).groups())
        i += 1
    if i >= len(words):
        return None, [], prefix
    if os.path.basename(words[i]) in WRAPPERS:
        # A wrapper's own options and arguments vary; the deleter is the first later word.
        for j in range(i + 1, len(words)):
            if os.path.basename(words[j]) in DELETERS | {"find"}:
                return os.path.basename(words[j]), words[j + 1:], prefix
        return os.path.basename(words[i]), words[i + 1:], prefix
    return os.path.basename(words[i]), words[i + 1:], prefix


def judge(command):
    """None to allow, or (reason, note) to deny."""
    assigned = {}
    for words in segments(command):
        name, args, prefix = command_words(words)
        if name is None:  # a pure assignment persists
            for var, val in prefix:
                assigned[var] = value_of(val, assigned)
            continue
        # A prefix assignment (`X=1 rm $X`) doesn't reach this command's own words.
        if name in ("export", "local", "declare", "readonly", "typeset"):
            for a in args:
                m = ASSIGN.match(a)
                if m:
                    assigned[m.group(1)] = value_of(m.group(2), assigned)
            continue
        if name == "for" and args:
            items = args[2:] if len(args) > 1 and args[1] == "in" else []
            assigned[args[0]] = TAINT if any(problem(w, assigned) for w in items) else None
            continue
        if name == "set" and args and (args[0] == "--" or not args[0].startswith(("-", "+"))):
            items = args[1:] if args[0] == "--" else args
            assigned["#positional"] = TAINT if any(problem(w, assigned) for w in items) else None
            continue
        if name in ("read", "mapfile", "readarray"):
            for a in args:
                if re.fullmatch(r"[A-Za-z_]\w*", a):
                    assigned[a] = None
            continue
        if name in DELETERS:
            paths = [a for a in args if not a.startswith("-") or a == "-"]
        elif name == "find" and deletes(args):
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


def deletes(find_args):
    for k, a in enumerate(find_args):
        if a == "-delete":
            return True
        if a in ("-exec", "-execdir", "-ok", "-okdir") and k + 1 < len(find_args) \
                and os.path.basename(find_args[k + 1]) in DELETERS:
            return True
    return False


def check(name, paths, assigned):
    for p in paths:
        why = problem(p, assigned)
        if why:
            return (f"delete-guard: this sandbox-off {name} deletes {p}, built from {why}. Spell "
                    "out the absolute path, or run the delete sandboxed.",
                    f"deny untrusted {name} {p}")
        target = expand(p, assigned)
        if target is not None and is_catastrophic(target):
            return (f"delete-guard: this sandbox-off {name} would delete {p} ({target}), a "
                    "top-level or home tree. Name the specific path inside it.",
                    f"deny catastrophic {name} {target}")
    return None


def catastrophic():
    home = os.path.expanduser("~")
    tops = {"/", "/tmp", "/var", "/usr", "/etc", "/opt", "/bin", "/lib", "/boot", "/root",
            "/home", "/mnt", "/mnt/c", "/mnt/c/Users", "/srv", "/proc", "/sys", "/dev"}
    trees = {home} | {os.path.join(home, d) for d in (
        ".claude", ".config", ".local", ".local/share", ".local/state", ".ssh", "code", "dotclaude",
        "scratch", "vault", ".codex", ".cache")}
    return tops | trees


def is_catastrophic(target):
    """A top-level or home tree itself, or a glob directly inside one (`~/*`, `~/.*`)."""
    target = "/" + os.path.normpath(target).lstrip("/") if target.startswith("/") else \
        os.path.normpath(target)
    if re.search(r"[*?\[]", os.path.basename(target)):
        target = os.path.dirname(target) or "/"
    return target in catastrophic()


def expand(p, assigned):
    """The path with ~ and the command's literal assignments (or HOME, USER) filled in; None when
    a value isn't known from the command text."""
    values = dict({v: os.environ.get(v) for v in STABLE}, **assigned)

    def literal(m):
        value = values.get(m.group(1) or m.group(2))
        if not isinstance(value, str) or "$" in value or SUBST in value:
            raise LookupError
        return value
    try:
        p = re.sub(r"\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)", literal, p)
    except LookupError:
        return None
    return os.path.expanduser(p)


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
