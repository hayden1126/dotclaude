"""Reading a Bash command as simple commands, shared by delete_guard.py and practices_check.py.

One quote-aware pre-pass joins backslash-newline continuations, drops `#` comments, skips
heredoc bodies, replaces each $(...), `...`, $((...)) and $'...' with a placeholder, and marks
each redirection (`>`, `>>`, `<`, `2>&1`, `&>`, `<<<`, an fd digit before one); then shlex splits
the result into simple commands (segments), leaving out each redirection and its target, so a
command's positional words stay its own (`git push 2>&1` names no remote "2"). command_words()
finds the command a segment runs through prefix assignments, shell keywords and wrappers
(`sudo -u x`, `env -i`, `timeout 30`, `time -p`), and cd_target() follows a `cd`. git_call()
reads a git command's global options (-C, --git-dir, --work-tree, a GIT_DIR= prefix) and its
subcommand.

calls() (practices_check) goes further: it reads the body of each $(...), `...`, <(...) and
>(...) as commands, from the cwd in force where it sits (nested up to NEST_MAX deep), and a
`bash -c`, `sh -c` or `zsh -c` script the outer shell passes as written; it follows `env -C`
and `sudo -D` for their command alone, and a `cd` inside `( ... )` ends at the `)`. With rest,
it hands back every argument text and heredoc body, so its caller can log a command it names
but can't read. segments() (delete_guard) keeps the old shape: a substitution is one
placeholder, and a process substitution's parentheses split its body into segments.

Accepted limits (accidents, not an adversary, are the target): a command run by `eval`, an
alias, a function (its body's `cd` is read as if it ran) or a script file; one a launcher
runs (`xargs`, `find -exec`, `git submodule foreach`, `ssh host`), a `bash -c` script with
an expansion in it, or one fed on stdin (`bash <<EOF`), which calls() leaves to rest; a
command inside an unquoted heredoc's $(...); a `)` inside `$(case ...)`; a literal `%SUBST%`
in the command, which can give a substitution the wrong cwd. Stdlib only.
"""
import os
import re
import shlex

# Words that can precede the command itself: the shell keywords that open a body, and wrappers.
KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{"}
WRAPPERS = {"sudo", "doas", "command", "nohup", "env", "builtin", "exec", "timeout", "nice",
            "ionice", "stdbuf", "chronic", "time"}  # time: bash's keyword (-p) or GNU time
# The short options of each wrapper known to take an argument (`sudo -u x`, `sudo -R /x`). They
# tell `-uroot` (the argument attached) from `-Eu` (the next word is the argument). The walk is
# conservative: any other option, and any long one without `=value`, may take the next word too,
# so that word is skipped unless it names a command the caller looks for (`sudo -E git`).
WRAPPER_ARGS = {"sudo": "RcaDghprtTUuC", "doas": "aCu", "env": "uCS", "timeout": "ks",
                "nice": "n", "ionice": "cnp", "stdbuf": "ioe", "exec": "a", "time": "fo"}
# The short option that names the dir a wrapper runs the command in (also --chdir).
CHDIR = {"env": "C", "sudo": "D"}
# The shells whose `-c 'script'` calls() reads as commands, and the options that take a word.
SHELLS = {"bash", "sh", "zsh"}
SHELL_ARG_OPTS = {"-o", "+o", "-O", "+O", "--rcfile", "--init-file"}
# Placeholders. They start with a character no variable name can hold, so `$p$(date)` stays two
# parts; shlex keeps % inside a word.
SUBST, ANSI, ARITH, REDIR = "%SUBST%", "%ANSI%", "%ARITH%", "%REDIR%"
ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.S)
COUNT = re.compile(r"\d+(\.\d+)?[smhd]?")  # `timeout 30s`, `nice -n 5`
HEREDOC = re.compile(r"<<(-?)\s*(?:'([^']*)'|\"([^\"]*)\"|\\?([A-Za-z_0-9.-]+))")
# A redirection: an fd digit (only at a word start) before <<<, <>, <&, >>, >&, >|, < or >; or
# &> and &>>. A heredoc's << has its own branch, and <( and >( are process substitutions.
REDIRECT = re.compile(r"(\d*)(?:<<<|<>|<&|>>|>&|>\||<(?![<(])|>(?!\())|&>>?")


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


def _body(s, start, end, close):
    """The text from start to the closing character just before end, or to end when the text
    ran out first (an unclosed substitution)."""
    return s[start:end - 1] if end - 1 >= start and s[end - 1:end] == close else s[start:end]


def prepass(command, bodies=None, heredocs=None):
    """The command with continuations joined, comments dropped, heredoc bodies skipped, and each
    $(...), `...`, $((...)) and $'...' replaced by a placeholder, all outside single quotes.
    With bodies (a list), the text inside each $(...), `...`, <(...) and >(...) is appended to
    it in order, one per SUBST placeholder, and a process substitution is replaced too; without,
    a process substitution stays in the text, where its parentheses split the segments
    (delete_guard reads its body that way). With heredocs (a list), each skipped heredoc body
    is appended to it."""
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
        elif quote is None and bodies is not None and s.startswith(("<(", ">("), i):
            end = closing(s, i + 2)
            bodies.append(_body(s, i + 2, end, ")"))
            out.append(SUBST)
            i = end
            continue
        elif quote is None and (m := REDIRECT.match(s, i)) and (
                not m.group(1) or i == 0 or s[i - 1] in " \t\n;&|()"):
            out.append(f" {REDIR} ")  # segments() drops it and its target word
            i = m.end()
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
            end = skip_bodies(s, i + 1, pending)
            if heredocs is not None:
                heredocs.append(s[i + 1:end])
            i, pending = end, []
            continue
        if s.startswith("$((", i):
            i = closing(s, i + 3)
            i += s[i:i + 1] == ")"
            out.append(ARITH)
            continue
        if s.startswith("$(", i):
            end = closing(s, i + 2)
            if bodies is not None:
                bodies.append(_body(s, i + 2, end, ")"))
            out.append(SUBST)
            i = end
            continue
        if c == "`":
            end = skip_quoted(s, i + 1, "`")
            if bodies is not None:  # inside backticks, \\, \` and \$ stand for the character
                bodies.append(re.sub(r"\\([\\`$])", r"\1", _body(s, i + 1, end, "`")))
            out.append(SUBST)
            i = end
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _split(text):
    """Pre-passed text as ("words", words, n) for each simple command, n being how many SUBST
    placeholders its words and redirection targets hold, and ("(", None, 0) or (")", None, 0)
    for each parenthesis, in order. Each redirection and its target word are left out of the
    words. Raises ValueError (from shlex) on an unbalanced quote."""
    lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
    lex.whitespace = " \t\r"
    lex.wordchars += "$-./~*?[]{}=:+@%,^!#"
    lex.commenters = ""
    seg, target, n = [], False, 0
    for tok in lex:
        if tok == "\n" or (tok and set(tok) <= set(";&|()")):
            if seg or n:
                yield "words", seg, n
            seg, target, n = [], False, 0
            yield from ((c, None, 0) for c in tok if c in "()")
        elif tok == REDIR:
            target = True
        elif target:
            target = False  # the redirection's file or fd (`>out`, `2>&1`, `<<< "$msg"`)
            n += tok.count(SUBST)
        else:
            seg.append(tok)
            n += tok.count(SUBST)
    if seg or n:
        yield "words", seg, n


def segments(command):
    """Simple commands as word lists, split at ; && || | & ( ) and newlines, each redirection
    and its target word left out. Raises ValueError (from shlex) on an unbalanced quote."""
    for kind, words, _ in _split(prepass(command)):
        if kind == "words" and words:
            yield words


def _option_takes_arg(wrapper, w):
    """Whether a wrapper's option word w may take the next word as its argument: every option
    may, except one whose argument is attached (`--user=x`, `-uroot`, `-R/x`)."""
    if w.startswith("--"):
        return "=" not in w
    letters = WRAPPER_ARGS.get(wrapper, "")
    cluster = w[1:]
    for k, c in enumerate(cluster):
        if c in letters:
            return k == len(cluster) - 1  # `-uroot` carries its own argument
    return True  # an option the table doesn't know may take one (`sudo --foo /x rm`)


def _chdir(wrapper, w):
    """(the dir a wrapper's option word runs the command in, or None; whether the next word is
    that dir): `env -C dir`, `env -Cdir`, `sudo -D dir`, `--chdir=dir`, `--chdir dir`."""
    letter = CHDIR.get(wrapper)
    if letter is None or (w.startswith("--") and not w.startswith("--chdir")):
        return None, False
    if w == "--chdir":
        return None, True
    if w.startswith("--chdir="):
        return w.split("=", 1)[1], False
    cluster = w[1:]
    for k, c in enumerate(cluster):
        if c in WRAPPER_ARGS.get(wrapper, ""):
            if c != letter:
                return None, False  # another option takes the rest of the cluster
            return (cluster[k + 1:], False) if cluster[k + 1:] else (None, True)
    return None, False


def command_words(words, heads=frozenset(), dirs=None):
    """(name, args, prefix assignments) of a simple command; name is None for a pure assignment.
    Through wrappers (`sudo -u x git`, `env -i git`, `timeout 60 git`, `nice git`), the wrapped
    command counts: options, assignments and counts are skipped, and so is the word after an
    option (its argument, _option_takes_arg) unless that word names one of heads, the commands
    the caller looks for. An option word is never taken as another option's argument. With
    dirs (a list), each dir a wrapper runs the command in (`env -C d`, `sudo -D d`) is
    appended to it, in order."""
    prefix, i = [], 0
    while i < len(words) and (ASSIGN.match(words[i]) or words[i] in KEYWORDS):
        if ASSIGN.match(words[i]):
            prefix.append(ASSIGN.match(words[i]).groups())
        i += 1
    if i >= len(words):
        return None, [], prefix
    while os.path.basename(words[i]) in WRAPPERS:
        wrapper = os.path.basename(words[i])
        j, wants_arg, wants_dir = i + 1, False, False
        while j < len(words):
            w, base = words[j], os.path.basename(words[j])
            if w == "--":
                j += 1
                break
            if wants_dir and not (w.startswith("-") and len(w) > 1):
                if dirs is not None:
                    dirs.append(w)  # `env -C git git push`: the dir, whatever it is named
                wants_arg = wants_dir = False
            elif w.startswith("-") and len(w) > 1:
                wants_arg = _option_takes_arg(wrapper, w)
                d, wants_dir = _chdir(wrapper, w)
                if d is not None and dirs is not None:
                    dirs.append(d)
            elif ASSIGN.match(w):
                wants_arg = False
                if wrapper in ("env", "time"):  # `env GIT_DIR=x git` sets it for the command
                    prefix.append(ASSIGN.match(w).groups())
            elif COUNT.fullmatch(w):
                wants_arg = False
            elif wants_arg and base not in heads | WRAPPERS:
                wants_arg = False  # the option's own argument (`-u x`)
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


def shell_script(args):
    """The script of `bash -c 'script'` (also sh and zsh, `-lc`, `-e -c`, `-o x -c`) when the
    outer shell passes it as written: no $, backtick or substitution placeholder in it. None
    otherwise, or when there is no -c."""
    c, i = False, 0
    while i < len(args):
        a = args[i]
        if a == "--":
            i += 1
            break
        if a in SHELL_ARG_OPTS:
            i += 2
            continue
        if a.startswith(("-", "+")) and len(a) > 1:
            c = c or (a[0] == "-" and not a.startswith("--") and "c" in a[1:])
            i += 1
            continue
        break
    if not c or i >= len(args):
        return None
    script = args[i]
    if "$" in script or "`" in script or any(p in script for p in (SUBST, ANSI, ARITH)):
        return None
    return script


NEST_MAX = 8  # substitutions nested this deep are read; deeper is an unparsable command


def calls(command, heads, cwd, rest=None, depth=0):
    """[(name, args, prefix, cwd)] for each simple command whose name is in heads, with the cwd
    each starts in (None once a cd can't be followed). The body of each $(...), `...`, <(...)
    and >(...) is read as commands too, from the cwd in force where it sits, before the command
    holding it (it runs first), and so is a literal `bash -c` script (shell_script); a cd
    inside either stays inside. With rest (a list), the words
    after each simple command's name, joined, and each heredoc body are appended to it, so a
    caller can tell a command it can't read (`xargs git push`) from no command at all; a body
    or script that can't be parsed (a shlex error, or nested deeper than NEST_MAX) goes to rest
    whole, and the rest of the command is still read. Raises ValueError when the command itself
    can't be parsed, and, without rest, when a body or script can't."""
    if depth > NEST_MAX:
        raise ValueError(f"substitutions nested over {NEST_MAX} deep")
    bodies, out, k, outer = [], [], 0, []

    def inner(text, where):
        try:
            return calls(text, heads, where, rest, depth + 1)
        except ValueError:
            if rest is None:
                raise
            rest.append(text)  # unread: the caller's log sees any call it names
            return []

    for kind, words, n in _split(prepass(command, bodies, rest)):
        if kind == "(":  # a subshell: a cd inside it ends with it
            outer.append(cwd)
            continue
        if kind == ")":
            cwd = outer.pop() if outer else cwd  # a case pattern's ) opens nothing
            continue
        for body in bodies[k:k + n]:
            out += inner(body, cwd)
        k += n
        if not words:
            continue
        dirs = []
        name, args, prefix = command_words(words, set(heads) | SHELLS, dirs)
        if name in ("cd", "pushd"):
            cwd = cd_target(args, cwd)
            continue
        here = cwd
        for d in dirs:  # `env -C d`, `sudo -D d`: this command only
            here = cd_target([d], here) if not d.startswith("-") else None
        script = shell_script(args) if name in SHELLS else None
        if script is not None:
            out += inner(script, here)
            continue
        if rest is not None:
            rest.append(" ".join(args))
        if name in heads:
            out.append((name, args, prefix, here))
    for body in bodies[k:]:  # a literal %SUBST% in the command leaves the count short
        out += inner(body, cwd)
    return out
