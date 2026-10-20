"""Reading a Bash command as simple commands, shared by delete_guard.py and practices_check.py.

One quote-aware pre-pass joins backslash-newline continuations, drops `#` comments, skips
heredoc bodies, and replaces each $(...), `...`, $((...)) and $'...' with a placeholder; then
shlex splits the result into simple commands (segments). command_words() finds the command a
segment runs through prefix assignments, shell keywords and wrappers (`sudo -u x`, `env -i`,
`timeout 30`), and cd_target() follows a `cd`. git_call() reads a git command's global options
(-C, --git-dir, --work-tree, a GIT_DIR= prefix) and its subcommand.

Accepted limits (accidents, not an adversary, are the target): a command inside `bash -c`,
`eval`, a function, an alias or a script; a `)` inside `$(case ...)`. Stdlib only.
"""
import os
import re
import shlex

# Words that can precede the command itself: the shell keywords that open a body, and wrappers.
KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "time"}
WRAPPERS = {"sudo", "doas", "command", "nohup", "env", "builtin", "exec", "timeout", "nice",
            "ionice", "stdbuf", "chronic"}
# The short options of each wrapper that take an argument (`sudo -u x`); any other option
# takes none (`sudo -E`, `env -i`), and a cluster ending in one of these takes the next word.
WRAPPER_ARGS = {"sudo": "ugCDhprtUT", "doas": "uC", "env": "uCS", "timeout": "ks", "nice": "n",
                "ionice": "cnp", "stdbuf": "ioe", "exec": "a"}
LONG_ARGS = {"--user", "--group", "--chdir", "--unset", "--split-string", "--kill-after",
             "--signal", "--adjustment", "--class", "--classdata", "--prompt", "--role", "--type",
             "--host", "--close-from", "--command-timeout", "--other-user", "--input", "--output",
             "--error", "--pid", "--pgid", "--uid"}
# Placeholders. They start with a character no variable name can hold, so `$p$(date)` stays two
# parts; shlex keeps % inside a word.
SUBST, ANSI, ARITH = "%SUBST%", "%ANSI%", "%ARITH%"
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
COUNT = re.compile(r"\d+(\.\d+)?[smhd]?")  # `timeout 30s`, `nice -n 5`
HEREDOC = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|\\?([A-Za-z_0-9.-]+))")


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
    """Simple commands as word lists, split at ; && || | & ( ) and newlines. Raises ValueError
    (from shlex) on an unbalanced quote."""
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


def _option_takes_arg(wrapper, w):
    """Whether a wrapper's option word w takes the next word as its argument."""
    if w.startswith("--"):
        return "=" not in w and w in LONG_ARGS
    letters = WRAPPER_ARGS.get(wrapper, "")
    cluster = w[1:]
    for k, c in enumerate(cluster):
        if c in letters:
            return k == len(cluster) - 1  # `-uroot` carries its own argument
    return False


def command_words(words, heads=frozenset()):
    """(name, args, prefix assignments) of a simple command; name is None for a pure assignment.
    Through wrappers (`sudo -u x git`, `env -i git`, `timeout 60 git`, `nice git`), the wrapped
    command counts: options, assignments and counts are skipped, and so is an option's argument
    (WRAPPER_ARGS) unless it names one of heads, the commands the caller looks for."""
    prefix, i = [], 0
    while i < len(words) and (ASSIGN.match(words[i]) or words[i] in KEYWORDS):
        if ASSIGN.match(words[i]):
            prefix.append(ASSIGN.match(words[i]).groups())
        i += 1
    if i >= len(words):
        return None, [], prefix
    while os.path.basename(words[i]) in WRAPPERS:
        wrapper = os.path.basename(words[i])
        j, wants_arg = i + 1, False
        while j < len(words):
            w, base = words[j], os.path.basename(words[j])
            if wants_arg and base not in heads | WRAPPERS:
                wants_arg = False  # the option's own argument (`-u x`)
            elif w == "--":
                j += 1
                break
            elif w.startswith("-") and len(w) > 1:
                wants_arg = _option_takes_arg(wrapper, w)
            elif ASSIGN.match(w):
                if wrapper == "env":  # `env GIT_DIR=x git` sets it for the command
                    prefix.append(ASSIGN.match(w).groups())
            elif COUNT.fullmatch(w):
                pass
            else:
                break
            j += 1
        if j >= len(words):
            break
        i = j
    return os.path.basename(words[i]), words[i + 1:], prefix


def literal(word):
    """[word's one value] when it has no expansion (variable, substitution, glob), with ~
    expanded; [] otherwise."""
    if "$" in word or any(p in word for p in (SUBST, ANSI, ARITH)) or re.search(r"[*?\[]", word):
        return []
    return [os.path.expanduser(word)]


def cd_arg(args):
    """The directory word a `cd` or `pushd` goes to ("~" for none), or None for `cd -`."""
    target = next((a for a in args if not a.startswith("-") or a == "-"), "~")
    return None if target == "-" else target


def cd_target(args, cwd, values=literal):
    """The cwd after a `cd` with these args: a normalized absolute path, or None when it can't
    be told. values(word) lists the word's possible values (literal() by default: the word
    itself when nothing in it expands). A relative target joins cwd when cwd is a path; any
    other cwd (a caller's sentinel, or None) comes back unchanged."""
    target = cd_arg(args)
    if target is None:
        return None
    known = values(target)
    if len(known) != 1:
        return None
    if known[0].startswith("/"):
        return os.path.normpath(known[0])
    return os.path.normpath(os.path.join(cwd, known[0])) if isinstance(cwd, str) else cwd


# --- git ---------------------------------------------------------------------------------------

GIT_ARG_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env",
                "--super-prefix", "--exec-path"}


class Unreadable(Exception):
    """A git location this parser can't resolve (a variable or a substitution in it)."""


def git_call(args, prefix, cwd):
    """(subcommand, its args, {"cwd", "git_dir", "work_tree"}) for git's argv after `git`, given
    its prefix assignments and the cwd it starts in (None when unknown), or None when there is
    no subcommand. Each -C applies in order, and --git-dir, --work-tree and GIT_DIR resolve
    against the cwd after them. Raises Unreadable when one of those holds an expansion."""
    where = {"cwd": cwd, "git_dir": None, "work_tree": None}
    env = dict(prefix)
    i = 0
    while i < len(args):
        a = args[i]
        if a in GIT_ARG_OPTS or (a.startswith("--") and a.split("=", 1)[0] in GIT_ARG_OPTS):
            if "=" in a and a.startswith("--"):
                opt, val = a.split("=", 1)
                i += 1
            elif i + 1 < len(args):
                opt, val = a, args[i + 1]
                i += 2
            else:
                return None
            if opt == "-C":
                if not literal(val):
                    raise Unreadable(f"git -C {val}")
                where["cwd"] = cd_target([val], where["cwd"]) if val else where["cwd"]
            elif opt in ("--git-dir", "--work-tree"):
                if not literal(val):
                    raise Unreadable(f"git {opt} {val}")
                where[opt[2:].replace("-", "_")] = val
            continue
        if a.startswith("-C") and len(a) > 2:  # `-Cdir`
            args = [*args[:i], "-C", a[2:], *args[i + 1:]]
            continue
        if a.startswith("-"):
            i += 1
            continue
        break
    if i >= len(args):
        return None
    for name in ("GIT_DIR", "GIT_WORK_TREE"):
        if name in env:
            if not literal(env[name]):
                raise Unreadable(f"{name}={env[name]}")
            key = "git_dir" if name == "GIT_DIR" else "work_tree"
            where[key] = where[key] or env[name]
    base = where["cwd"]
    for key in ("git_dir", "work_tree"):
        v = where[key]
        if v is not None:
            v = os.path.expanduser(v)
            if not v.startswith("/"):
                v = os.path.join(base, v) if isinstance(base, str) else None
                if v is None:
                    raise Unreadable(f"a relative {key} from an unknown cwd")
            where[key] = os.path.normpath(v)
    return args[i], args[i + 1:], where


def calls(command, heads, cwd):
    """[(name, args, prefix, cwd)] for each simple command whose name is in heads, with the cwd
    each starts in (None once a cd can't be followed). Raises ValueError on an unparsable
    command."""
    out = []
    for words in segments(command):
        name, args, prefix = command_words(words, heads)
        if name in ("cd", "pushd"):
            cwd = cd_target(args, cwd)
            continue
        if name in heads:
            out.append((name, args, prefix, cwd))
    return out
