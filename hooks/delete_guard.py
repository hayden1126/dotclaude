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

How it reads a command (hooks/bash_words.py, shared with practices_check.py): one quote-aware
pre-pass joins backslash-newline continuations, drops `#` comments, skips heredoc bodies, and
replaces each $(...), `...`, $((...)) and $'...' with a placeholder; then shlex splits the result
into simple commands. Accepted limits (accidents, not
an adversary, are the target): `xargs rm` (its paths come from stdin), a delete inside
`bash -c`, `eval`, a function or a script, a single-quoted '$X' (read as a variable: it can only
over-deny), a glob two levels down (`~/*/*`), an array assigned from an unset variable
(`a=($X)`), more than 64 brace or loop values, and a `)` inside `$(case ...)`.

Fails open: an error or an unparsable command allows the call and is logged, as is every deny,
to $XDG_STATE_HOME/dotclaude/delete-guard.log.
"""
import importlib.util
import itertools
import json
import os
import re
import sys
import time


def load_bash_words():
    """hooks/bash_words.py beside this file, loaded by its path and compiled from its source.
    python3 -I leaves this file's dir off sys.path, and it stays off: a planted shlex.py there
    would run outside the sandbox when bash_words imports shlex. No cached .pyc is read."""
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "bash_words.py")
    with open(path, encoding="utf-8") as f:
        source = f.read()
    mod = importlib.util.module_from_spec(importlib.util.spec_from_file_location("bash_words",
                                                                                 path))
    exec(compile(source, path, "exec"), mod.__dict__)  # noqa: S102 (our own module)
    return mod


bash_words = load_bash_words()
ASSIGN, SUBST, segments = bash_words.ASSIGN, bash_words.SUBST, bash_words.segments

DELETERS = {"rm", "rmdir", "shred", "unlink"}
STABLE = {"HOME", "USER"}
TAINT = object()      # a value built from something untrusted
EMPTYABLE = object()  # a lone command substitution, which can come back empty
UNKNOWN = object()    # set by the command, value unknown (read, a for over a substitution)
VAR = re.compile(r"\$(?:\{([^}]*)\}|([A-Za-z_][A-Za-z0-9_]*)|([0-9@*#?!-]))")
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
# bash_words.py has the pre-pass, the segment split and the wrapper walk.

def command_words(words):
    """(name, args, prefix assignments) of a simple command, through wrappers: an option's
    argument is skipped unless it names a deleter or find."""
    return bash_words.command_words(words, DELETERS | {"find"})


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
    target = bash_words.cd_arg(args)
    if target is not None:
        keys = [k for k, _, _ in refs(target)]
        if problem(target, state) or SUBST in target or \
                any(state["vars"].get(k) is EMPTYABLE for k in keys):
            return TAINT
    return bash_words.cd_target(args, state["cwd"], lambda w: candidates(w, state))


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
