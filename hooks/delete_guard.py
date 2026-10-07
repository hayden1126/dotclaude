"""PreToolUse(Bash) guard for deletes that run outside the sandbox; hooks/delete-guard.sh runs it.

Inside the sandbox a delete can only reach the working directory and $TMPDIR. A command run with
dangerouslyDisableSandbox can reach everything, and its variables can mean something else:
$TMPDIR is the sandbox's own directory only inside the sandbox, and plain /tmp outside it, so
there `rm -rf "$TMPDIR"/x` aims at /tmp/x (2026-10-06). So, for a sandbox-off command only, a
delete (rm, rmdir, shred, unlink, or find with -delete or -exec/-execdir/-ok rm) is denied when
one of its paths

  - uses a variable the command didn't set before the delete (`X=...`, `export X=`, `for X in`,
    `read X`, `set --` for $1 and $@), or one whose value was built from such a variable
    (`D="$TMPDIR/x"`). HOME and USER count as set unless the command reassigns them;
  - uses an operator expansion (`${X:-/tmp}`, `${X%/*}`), whose result can differ from how it
    reads. `${X:?}` (bash stops on an empty X) and `${X[@]}` read as plain X;
  - would widen if a command substitution, a `read` line, or a variable holding one came back
    empty: to a directory (`"$HOME/$d"` becomes `$HOME/`), an absolute path (`"$d"/x` becomes
    `/x`), a bare glob (`"$d"/*` becomes `/*`) or `.`/`..`. A lone `"$d"` only empties the
    argument, and `"$d".txt` stays in the working directory, so both pass;
  - is, after the command's own values, ~ and brace expansion, a catastrophic target: /, a
    top-level system directory, the home directory or one of its main trees (~/.claude, ~/code,
    ..., and a Windows home /mnt/c/Users/<name>), or a glob matching everything directly inside
    one (`~/*`, `~/.*`, `/tmp/?*`; a narrower `/tmp/pytest-*` is ordinary cleanup);
  - is relative, by its value (`for f in *; do rm -rf "$f"`), after a `cd` into an untrusted or
    possibly empty path (`cd "$TMPDIR" && rm -rf ./*`) or into a catastrophic target.

A find that filters what it deletes (-name, -path, -mtime, ...) is held only to the untrusted
rule: `find ~/code -name __pycache__ -exec rm -rf {} +` is ordinary cleanup.

Replayed over a month of transcripts (4367 sandbox-off Bash calls, 247 with a delete), it would
have denied 6, all a path built from $TMPDIR (directly, through a variable, or `${TMPDIR:-/tmp}`)
in a command where $TMPDIR was /tmp. A sandboxed command is never judged, and neither is any
other command: normal rm runs without prompts.

How it reads a command: one quote-aware pre-pass joins backslash-newline continuations, drops `#`
comments, skips heredoc bodies, and replaces each $(...), `...`, $((...)) and $'...' with a
placeholder; then shlex splits the result into simple commands. Accepted limits (accidents, not
an adversary, are the target): `xargs rm` (its paths come from stdin), a delete inside
`bash -c`, `eval`, a function or a script, a single-quoted '$X' (read as a variable: it can only
over-deny), a glob two levels down (`~/*/*`), an array assigned from an unset variable
(`a=($X)`), more than 64 brace or loop values, and a `)` inside `$(case ...)`.

Fails open: an error or an unparsable command allows the call and is logged, as is every deny,
to $XDG_STATE_HOME/dotclaude/delete-guard.log.
"""
import itertools
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
# Placeholders. They start with a character no variable name can hold, so `$p$(date)` stays two
# parts; shlex keeps % inside a word.
SUBST, ANSI, ARITH = "%SUBST%", "%ANSI%", "%ARITH%"
TAINT = object()      # a value built from something untrusted
EMPTYABLE = object()  # a lone command substitution, which can come back empty
UNKNOWN = object()    # set by the command, value unknown (read, a for over a substitution)
VAR = re.compile(r"\$(?:\{([^}]*)\}|([A-Za-z_][A-Za-z0-9_]*)|([0-9@*#?!-]))")
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
FIND_FILTERS = {"-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex",
                "-iregex", "-newer", "-mtime", "-mmin", "-user", "-size", "-empty"}
MAX_CANDIDATES = 64


def log(line):
    try:
        d = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "delete-guard.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


# --- Reading the command ----------------------------------------------------------------------

def skip_quoted(s, i, quote, escapes=None):
    """Index just past the quote that closes one opened before i. Backslash escapes count except
    in single quotes; $'...' passes escapes=True, since there \\' is an escaped quote."""
    escapes = quote != "'" if escapes is None else escapes
    while i < len(s):
        if s[i] == "\\" and escapes:
            i += 2
            continue
        if s[i] == quote:
            return i + 1
        i += 1
    return i


def closing(s, i):
    """Index just past the `)` that closes a `$(` opened before i: nested parentheses count,
    while quotes, comments, escapes and heredoc bodies are skipped."""
    depth, pending = 1, []
    while i < len(s) and depth:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c in "'\"`":
            i = skip_quoted(s, i + 1, c)
            continue
        if c == "#" and (s[i - 1] in " \t\n;&|("):
            while i < len(s) and s[i] != "\n":
                i += 1
            continue
        if s.startswith("<<<", i):
            i += 3
            continue
        if s.startswith("<<", i):
            m = HEREDOC.match(s, i)
            if m:
                pending.append(delimiter(m))
                i = m.end()
                continue
        if c == "\n" and pending:
            i = skip_bodies(s, i + 1, pending)
            pending = []
            continue
        depth += c == "("
        depth -= c == ")"
        i += 1
    return i


def delimiter(m):
    return next(g for g in m.groups()[1:] if g is not None)


def skip_bodies(s, i, pending):
    """Index just past the heredoc bodies that start at i, one per pending delimiter: each runs
    to a line holding only its delimiter."""
    for end in pending:
        while i < len(s):
            j = s.find("\n", i)
            line, i = (s[i:], len(s)) if j == -1 else (s[i:j], j + 1)
            if line.strip() == end:
                break
    return i


HEREDOC = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|\\?([A-Za-z_0-9.-]+))")


def prepass(command):
    """The command with continuations joined, comments dropped, heredoc bodies skipped, and each
    $(...), `...`, $((...)) and $'...' replaced by a placeholder, all outside single quotes."""
    s, out, i, quote, pending = command, [], 0, None, []
    while i < len(s):
        c = s[i]
        if quote == "'":
            quote = None if c == "'" else quote
            out.append(c)
            i += 1
            continue
        if c == "\\":
            if s[i + 1:i + 2] == "\n":
                i += 2
                continue
            out.append(s[i:i + 2])
            i += 2
            continue
        if c == '"':
            quote = None if quote == '"' else '"'
        elif quote is None and c == "'":
            quote = "'"
        elif quote is None and s.startswith("$'", i):
            i = skip_quoted(s, i + 2, "'", escapes=True)
            out.append(ANSI)
            continue
        elif quote is None and c == "#" and (i == 0 or s[i - 1] in " \t\n;&|("):
            while i < len(s) and s[i] != "\n":
                i += 1
            continue
        elif quote is None and s.startswith("<<<", i):  # a here-string, not a heredoc
            out.append("<<<")
            i += 3
            continue
        elif quote is None and s.startswith("<<", i):
            line = "".join(out).rsplit("\n", 1)[-1]
            m = None if line.count("((") > line.count("))") else HEREDOC.match(s, i)  # a shift
            if m:
                pending.append(delimiter(m))
                out.append(" ")
                i = m.end()
                continue
        elif quote is None and c == "\n" and pending:
            out.append("\n")
            i = skip_bodies(s, i + 1, pending)
            pending = []
            continue
        if s.startswith("$((", i):
            i = closing(s, i + 3)
            i += s[i:i + 1] == ")"
            out.append(ARITH)
            continue
        if s.startswith("$(", i):
            i = closing(s, i + 2)
            out.append(SUBST)
            continue
        if c == "`":
            i = skip_quoted(s, i + 1, "`")
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
        if tok == "\n" or (tok and set(tok) <= set(";&|()")):
            if seg:
                yield seg
            seg = []
        else:
            seg.append(tok)
    if seg:
        yield seg


def command_words(words):
    """(name, args, prefix assignments) of a simple command; name is None for a pure assignment.
    Through wrappers (`sudo -u x rm`, `timeout 60 rm`, `nice rm`), the wrapped command counts: an
    option, an assignment and a count are skipped, and so is the word after an option unless it
    names a deleter."""
    prefix, i = [], 0
    while i < len(words) and (ASSIGN.match(words[i]) or words[i] in KEYWORDS):
        if ASSIGN.match(words[i]):
            prefix.append(ASSIGN.match(words[i]).groups())
        i += 1
    if i >= len(words):
        return None, [], prefix
    while os.path.basename(words[i]) in WRAPPERS:
        j, after_option = i + 1, False
        while j < len(words):
            w, base = words[j], os.path.basename(words[j])
            if w.startswith("-"):
                after_option = True
            elif ASSIGN.match(w) or re.fullmatch(r"\d+(\.\d+)?[smhd]?", w):  # `timeout 30s`
                after_option = False
            elif after_option and base not in DELETERS | {"find"} | WRAPPERS:
                after_option = False  # the option's own argument (`-u x`)
            else:
                break
            j += 1
        if j >= len(words):
            break
        i = j
    return os.path.basename(words[i]), words[i + 1:], prefix


# --- Judging values ---------------------------------------------------------------------------

PLAIN_BRACE = re.compile(r"([A-Za-z_]\w*)(:?\?[^}]*|\[[^\]]*\])?")


def key_of(brace, name, special):
    """The variable a reference reads: $1, $@ map to #pos; ${X:?} and ${X[@]} read X."""
    if special:
        return "#pos" if special.isdigit() or special in "@*" else "$" + special
    if brace:
        m = PLAIN_BRACE.fullmatch(brace)
        return m.group(1) if m else re.match(r"[A-Za-z_]\w*|", brace).group()
    return name


def refs(text):
    """The variables text reads: (key, operator expansion?, guarded?) per reference. ${X:?} is
    guarded (bash stops on an empty X, so it can't widen a path); ${X[@]} reads the array X; any
    other operator (${X:-/tmp}, ${X%/*}) can come back other than it reads."""
    out = []
    for brace, name, special in VAR.findall(text):
        m = PLAIN_BRACE.fullmatch(brace) if brace else None
        out.append((key_of(brace, name, special), bool(brace) and not m,
                    bool(m and m.group(2) and "?" in m.group(2))))
    return out


def problem(text, state):
    """Why text can't be trusted as a path, or None."""
    vals = state["vars"]
    empty = []
    for key, operator, guarded in refs(text):
        if operator:
            return f"an expansion with an operator, ${{{key}...}}, whose result can differ from how it reads"
        if key.startswith("$") and key not in ("$$",):
            return f"{key}, which this command doesn't set"
        if key in STABLE and key not in vals:
            continue
        if key not in vals:
            if key == "#pos":
                return "a positional parameter ($1, $@) this command doesn't set"
            hint = " (outside the sandbox $TMPDIR is plain /tmp)" if key == "TMPDIR" else ""
            return f"${key}, which this command doesn't set{hint}"
        if vals[key] is TAINT:
            return (f"${key if key != '#pos' else '1'}, whose value was built from an untrusted "
                    "part (a variable this command doesn't set)")
        if vals[key] is EMPTYABLE and not guarded:
            empty.append(key)
    if (empty or SUBST in text) and widens(text, empty, state):
        what = "a command substitution" if SUBST in text and not empty else \
            f"${empty[0]}, which holds a command substitution,"
        return f"{what} that can come back empty and widen this path to {residue(text, empty)!r}"
    return None


def residue(text, empty):
    """The path as it reads if every emptyable part comes back empty."""
    text = text.replace(SUBST, "")
    for key in empty:
        pat = r"\$(?:[0-9@*]|\{[0-9@*]\})" if key == "#pos" else \
            r"\$(?:\{%s\}|%s(?![A-Za-z0-9_]))" % (re.escape(key), re.escape(key))
        text = re.sub(pat, "", text)
    return text


def widens(text, empty, state):
    rest = residue(text, empty)
    if not rest:
        return False  # the argument itself becomes empty, which rm refuses
    starts_empty = text.startswith(SUBST) or (empty and re.match(r"\$\{?(%s)(?![A-Za-z0-9_])" % "|".join(
        re.escape(k) if k != "#pos" else r"[0-9@*]" for k in empty), text))
    for cand in candidates(rest, state) or [rest]:
        first = cand.split("/")[0]
        if (cand.endswith("/") or (starts_empty and cand.startswith(("/", "~")))
                or first in (".", "..") or re.fullmatch(r"[*?.\[\]]*", os.path.basename(cand))
                or is_catastrophic(cand)):
            return True
    return False


def value_of(text, state):
    """What an assignment stores: TAINT, EMPTYABLE, or the candidate values of its text."""
    if problem(text, state):
        return TAINT
    keys = [k for k, _, _ in refs(text)]
    if text == SUBST or (SUBST in text and not text.replace(SUBST, "")) or \
            any(state["vars"].get(k) is EMPTYABLE for k in keys):
        return EMPTYABLE
    if SUBST in text or any(state["vars"].get(k) is UNKNOWN for k in keys):
        return UNKNOWN
    return tuple(candidates(text, state, expand_home=False)) or UNKNOWN


def candidates(text, state, expand_home=True):
    """Every value text can take with the command's known values, brace expansion and ~; empty
    when some part is unknown."""
    vals = state["vars"]
    options = [text]
    for _ in range(8):  # values can name other variables
        nxt = []
        for t in options:
            m = VAR.search(t)
            if not m:
                nxt.append(t)
                continue
            brace, name, special = m.groups()
            key = key_of(brace, name, special)
            if key in STABLE and key not in vals:
                values = [os.environ.get(key, "")]
            else:
                v = vals.get(key)
                if not isinstance(v, tuple):
                    return []
                values = list(v)
                if special and special.isdigit() and special != "0":
                    k = int(special) - 1
                    values = [v[k]] if k < len(v) else [""]
            nxt += [t[:m.start()] + x + t[m.end():] for x in values]
        options = nxt[:MAX_CANDIDATES]
    if any(VAR.search(t) for t in options):
        return []
    out = []
    for t in options:
        for b in braces(t):
            out.append(os.path.expanduser(b) if expand_home else b)
    return out[:MAX_CANDIDATES]


def braces(text):
    """Bash brace expansion of the simple comma form: `~/{code,vault}` -> two paths."""
    m = re.search(r"\{([^{}]*,[^{}]*)\}", text)
    if not m:
        return [text]
    return list(itertools.chain.from_iterable(
        braces(text[:m.start()] + part + text[m.end():]) for part in m.group(1).split(",")))


def catastrophic():
    home = os.path.expanduser("~")
    tops = {"/", "/tmp", "/var", "/usr", "/etc", "/opt", "/bin", "/lib", "/boot", "/root",
            "/home", "/mnt", "/mnt/c", "/mnt/c/Users", "/srv", "/proc", "/sys", "/dev"}
    trees = {home} | {os.path.join(home, d) for d in (
        ".claude", ".config", ".local", ".local/share", ".local/state", ".ssh", "code", "dotclaude",
        "scratch", "vault", ".codex", ".cache")}
    return tops | trees


def is_catastrophic(target):
    """A top-level or home tree itself (a Windows home, /mnt/c/Users/<name>, too), or a glob that
    matches everything directly inside one (`~/*`, `~/.*`, `/tmp/?*`). A narrower glob
    (`/tmp/pytest-*`) is ordinary cleanup."""
    target = os.path.expanduser(target)
    if not target.startswith("/"):
        return False
    target = "/" + os.path.normpath(target).lstrip("/")
    if re.fullmatch(r"[*?.\[\]!]*", os.path.basename(target)):
        target = os.path.dirname(target) or "/"
    return target in catastrophic() or bool(re.fullmatch(r"/mnt/[a-z]/Users/[^/]+", target))


# --- The walk ---------------------------------------------------------------------------------

def judge(command):
    """None to allow, or (reason, note) to deny."""
    # cwd: None (unchanged or unknown), TAINT, or a known path. $_ (the last argument) is set.
    state = {"vars": {"_": UNKNOWN}, "cwd": None}
    for words in segments(command):
        name, args, prefix = command_words(words)
        if name is None:  # a pure assignment persists; a prefix one doesn't reach its command
            for var, val in prefix:
                state["vars"][var] = value_of(val, state)
            continue
        vals = state["vars"]
        if name in ("export", "local", "declare", "readonly", "typeset"):
            for a in args:
                m = ASSIGN.match(a)
                if m:
                    vals[m.group(1)] = value_of(m.group(2), state)
            continue
        if name == "for" and args:
            items = args[2:] if len(args) > 1 and args[1] == "in" else []
            vals[args[0]] = loop_value(items, state)
            continue
        if name == "set" and args and (args[0] == "--" or not args[0].startswith(("-", "+"))):
            items = args[1:] if args[0] == "--" else args
            vals["#pos"] = loop_value(items, state)
            if vals["#pos"] is UNKNOWN and any(SUBST in w for w in items):
                vals["#pos"] = EMPTYABLE  # `set -- $(cmd)` leaves $1 empty when cmd prints nothing
            continue
        if name in ("read", "mapfile", "readarray"):
            for a in args:
                if re.fullmatch(r"[A-Za-z_]\w*", a):
                    vals[a] = EMPTYABLE  # a blank line reads as empty
            continue
        if name in ("cd", "pushd"):
            state["cwd"] = cd_target(args, state)
            continue
        filtered = False
        if name in DELETERS:
            paths = [a for a in args if not a.startswith("-") or a == "-"]
        elif name == "find" and deletes(args):
            paths = find_roots(args)
            filtered = any(a in FIND_FILTERS for a in args)
        else:
            continue
        verdict = check(name, paths, state, filtered)
        if verdict:
            return verdict
    return None


def cd_target(args, state):
    """The cwd after a cd: TAINT into an untrusted or possibly empty path (`cd "$(mktemp -d)"`
    stays put when mktemp prints nothing), a known path, or None when it can't be told."""
    target = next((a for a in args if not a.startswith("-") or a == "-"), "~")
    if target == "-":
        return None
    keys = [k for k, _, _ in refs(target)]
    if problem(target, state) or SUBST in target or \
            any(state["vars"].get(k) is EMPTYABLE for k in keys):
        return TAINT
    known = candidates(target, state)
    if len(known) != 1:
        return None
    if known[0].startswith("/"):
        return os.path.normpath(known[0])
    cwd = state["cwd"]
    return cwd if cwd is TAINT else (os.path.normpath(os.path.join(cwd, known[0]))
                                     if isinstance(cwd, str) else None)


def loop_value(items, state):
    """The value a for variable (or $1, $@ after set --) takes over items."""
    if any(problem(w, state) for w in items):
        return TAINT
    values = []
    for w in items:
        c = candidates(w, state, expand_home=False)
        if not c or SUBST in w:
            return UNKNOWN
        values += c
    return tuple(values)


def find_roots(args):
    roots, k = [], 0
    while k < len(args) and args[k] in ("-L", "-H", "-P", "-D", "-O") or \
            (k < len(args) and re.fullmatch(r"-O\d", args[k])):
        k += 2 if args[k] == "-D" else 1
    for a in args[k:]:
        if a.startswith(("-", "(", "!")):
            break
        roots.append(a)
    return roots or ["."]


def deletes(find_args):
    for k, a in enumerate(find_args):
        if a == "-delete":
            return True
        if a in ("-exec", "-execdir", "-ok", "-okdir") and k + 1 < len(find_args) \
                and os.path.basename(find_args[k + 1]) in DELETERS:
            return True
    return False


def check(name, paths, state, filtered=False):
    """A deny for the first untrusted or catastrophic path. A find that filters what it deletes
    (`-name`, `-path`, ...) is only held to the untrusted rule: `find ~/code -name __pycache__
    -exec rm -rf {} +` is ordinary cleanup."""
    for p in paths:
        why = problem(p, state)
        if why:
            return (f"delete-guard: this sandbox-off {name} deletes {p}, built from {why}. Spell "
                    "out the absolute path, or run the delete sandboxed.",
                    f"deny untrusted {name} {p}")
        if filtered:
            continue
        cands = candidates(p, state)
        for target in cands:
            if is_catastrophic(target):
                return (f"delete-guard: this sandbox-off {name} would delete {p} ({target}), a "
                        "top-level or home tree. Name the specific path inside it.",
                        f"deny catastrophic {name} {target}")
        # Relative paths, judged by their values: `for f in *; do rm -rf "$f"` deletes relative ones.
        relative = [c for c in cands if not c.startswith("/")] if cands else \
            ([p] if not p.startswith(("/", "~", "$")) else [])
        cwd = state["cwd"]
        if relative and cwd is TAINT:
            return (f"delete-guard: this sandbox-off {name} deletes {p} relative to a cd into a "
                    "path this command doesn't set, or one that can come back empty. Spell out "
                    "the absolute path.", f"deny untrusted-cwd {name} {p}")
        for rel in relative if isinstance(cwd, str) else []:
            if is_catastrophic(os.path.join(cwd, rel)):
                return (f"delete-guard: this sandbox-off {name} would delete {p} inside {cwd}, a "
                        "top-level or home tree. Name the specific path inside it.",
                        f"deny catastrophic {name} {os.path.join(cwd, rel)}")
    return None


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
