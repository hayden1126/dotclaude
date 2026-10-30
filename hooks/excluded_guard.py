"""PreToolUse(Bash) guard for excluded commands; hooks/excluded-guard.sh runs it.

Rule: a command that runs outside the sandbox (one matching `sandbox.excludedCommands`) must not
act on anything a sandboxed session can write. For a call that matches, three checks:

  1. The git config the cwd resolves to. A repo at the cwd must be the project's own repository
     (same common git dir as CLAUDE_PROJECT_DIR); a nested repo, a planted gitfile or a repo in a
     temp dir is refused. Every other config file git reads (global, XDG, system, each
     include.path / includeIf.*.path target, recursively, and a core.hooksPath dir and each file
     in it) must be protected, judged along its symlink chain: each hop and the dir of each. Any
     path that exists is judged; only a regular file is parsed. The project repo's own config
     and hooks/ are trusted (Claude Code protects them for the session), and so is
     config.worktree when the cwd's gitdir is the project's own; another worktree's is judged.
     That trust rests on Claude Code protecting the session's gitfile and its
     worktrees/<name>/commondir, not the main .git/ dir, so the common dir comes from git's real
     layout: a gitdir with a commondir file must sit at <common>/worktrees/<name> with its
     commondir naming that <common>, and <common> must hold no commondir. Any other layout, in
     the cwd's repo or the project's, is refused. A path argument a head runs git in is judged
     the same way, resolved from the cwd (path_arguments: pass-respawn -C, lane adopt PATH, a
     local repository for git push, fetch, pull and ls-remote), and such a call must spell its
     words plainly, naming no program for git to run (--receive-pack, --upload-pack, --exec,
     an ext:: remote), no submodule recursion and no remote from a legacy .git/remotes or
     .git/branches file (check_git_words); a git repository is judged where git's server side
     finds it (<path>, <path>.git, a gitfile, a file:// URL with no host, no %-escape), and
     a git option before those subcommands is refused. The calls are found the way zsh splits
     the command (ShellLexer): each call of those heads anywhere in a candidate is judged, one
     in a substitution, subshell or later piece too, and a command it can't read is refused.
     `delegation-ledger hook` is refused outright, since its paths come on stdin.
  2. The PATH the head resolves through. Every PATH entry must be protected, not only those
     before the head: its children (git, gh, tmux, the tools claude spawns) search PATH too. An
     empty or relative entry is the cwd: refused. Then the resolved file's symlink chain (each
     hop and the dir of each) and a shebang interpreter (`#!/usr/bin/env X` resolves X through
     PATH), depth capped at 3.
  3. `claude` and `codex` run only from the project root.

Protected means not writable in the machine view. A path (or, if missing, its nearest existing
ancestor, at its target when that ancestor is a symlink) is writable when it sits under a root
($HOME, /tmp, $TMPDIR or an allowWrite entry; realpaths compared), no protecting entry,
~/.claude or ~/.gitconfig covers it, and some component from it up to its root is owned by the
user or writable by the user. A protecting entry is an `Edit(//abs/dir/**)` or `Edit(~/dir/**)`
deny rule with no symlink along its path, which binds sandboxed Bash and the Edit and Write
tools, or a denyWrite line inside
dotclaude's own checkouts (this guard's, and ~/dotclaude): a denyWrite line binds Bash only, and
dotclaude's hooks run outside the sandbox on every call anyway. Permission bits are not
protection: an owner can chmod a dir back, and a writable parent can rename it. Outside every
root is protected (/usr/bin, /etc). ~/.gitconfig counts only as a regular file at that exact
path; a symlink there is judged by its hops and target. PATH dirs are shared by every session,
so "this session can't write it" is not enough.

Which calls are candidates: a pattern's `*` matches any characters, spaces included; the rest is
literal. A call is a candidate when the whole command matches, or any piece does after splitting
on newlines, `;`, `&&`, `||`, `|` and `&` (not quote-aware, so it over-matches: an over-match only
adds checks to a sandboxed call). excludedCommands and allowWrite are the union of user, managed,
project and project-local files (more candidates, more writable: both safe). Protecting entries
count only from user and managed files: the machine view stands for every session, and other
sessions don't load this project's settings.

Fails closed for candidates: any error while matching makes the call a candidate, and any error
while checking one refuses it. A non-candidate exits silently. An unreadable payload raises, so
the shim's head-word fallback decides. Denies go to $XDG_STATE_HOME/dotclaude/excluded-guard.log.
"""
import contextlib
import fcntl
import glob
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time

MANAGED_DIR = "/etc/claude-code"
MANAGED_ENV = "EXCLUDED_GUARD_MANAGED_DIR"  # tests point this at a temp dir
SPLIT = re.compile(r"\n|&&|\|\||;|\||&")
ASSIGN = re.compile(r"""[A-Za-z_][A-Za-z0-9_]*=("[^"]*"|'[^']*'|\S*)\s*""")
PROJECT_HEADS = {"claude", "codex"}
SHEBANG_DEPTH = 3
INCLUDE_DEPTH = 10


def log(line):
    try:
        d = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "excluded-guard.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


# `Edit(//abs/dir/**)` or `Edit(~/dir/**)`. Claude Code merges an Edit deny rule into the
# sandbox's write denials and its Edit and Write tools refuse the path, so the rule binds both
# routes. Other forms (one file, project-relative, globs mid-path) are not read: a file's dir
# must be protected too, so a one-file rule never clears a refusal.
EDIT_RULE = re.compile(r"Edit\((//|~/)([^*?\[\]]*?)/?/\*\*\)")
# Where to rerun setup after a fix. It never names the lane holding the install when it prints:
# that goes stale once the lead's reinstall releases the hold (a rerun from merged lane
# pass-timeout took the install back, 2026-10-15). install-state.py refuses such a rerun too.
RERUN = ("rerun setup from the main checkout (`./setup.sh`), or, if `lane ls` shows an unmerged "
         "lane holding the install when you rerun, from that lane "
         "(`lane lock install -- ./setup.sh`)")
PROTECT_HINT = ("Add the permissions.deny rule {rule} to user or managed settings (a project's "
                "own don't count): it binds sandboxed Bash and the Edit and Write tools. "
                "dotclaude: ~/.claude/settings.machine.json, then " + RERUN)


def edit_rule_path(rule, home):
    """The dir a deny rule in EDIT_RULE's form covers, with everything under it, or None."""
    m = EDIT_RULE.fullmatch(rule) if isinstance(rule, str) else None
    if not m:
        return None
    # rstrip: a home of / would give //x, which normpath keeps as two slashes.
    return os.path.normpath(("/" if m.group(1) == "//" else home.rstrip("/") + "/") + m.group(2))


def protect_dir(path, roots=()):
    """The real dir an Edit deny rule covers to protect `path`: the dir it is or, for a file or
    a link, the dir holding it. None when that dir is a write root or above one, since the rule
    would cover the whole root, or when its name holds a glob character."""
    home = os.path.realpath(os.path.expanduser("~"))
    leaf = os.path.islink(path) or (os.path.lexists(path) and not os.path.isdir(path))
    d = os.path.realpath(os.path.dirname(path) if leaf else path)
    if any(under(r, d) for r in [*roots, home]) or re.search(r"[*?\[\]]", d):
        return None
    return d


def edit_rule(d):
    """The rule for the real dir `d`: the `~/` form only when $HOME holds no symlink, since a
    `~/` rule counts only then (Machine)."""
    home = os.path.abspath(os.path.expanduser("~"))
    if os.path.realpath(home) == home and under(d, home):
        return f"Edit(~/{os.path.relpath(d, home)}/**)"
    return f"Edit(/{d}/**)"


class Refusal(Exception):
    def __init__(self, rule, path, reason, protect=None):
        # protect: the Machine, when the fix is to write-protect `path`; name the rule that does.
        self.fix_dir = protect_dir(path, getattr(protect, "roots", ())) if protect else None
        self.fix = edit_rule(self.fix_dir) if self.fix_dir else None
        if self.fix:
            reason = f"{reason} {PROTECT_HINT.format(rule=self.fix)}."
        elif protect:
            reason = (f"{reason} Move it into a dir an Edit deny rule can protect (a rule can't "
                      "cover a write root itself or a name with a glob character).")
        super().__init__(reason)
        self.rule, self.path, self.reason = rule, path, reason


# --- Settings ----------------------------------------------------------------------------------

def expand(path, home):
    if path == "~" or path.startswith("~/"):
        return home + path[1:]
    return path


def load_settings(env):
    """Union of excludedCommands and allowWrite from user, managed, project and project-local
    settings; denyWrite and Edit deny rules (editDeny, as paths) from user and managed only.
    Returns (settings, errors): a file that
    exists but can't be read makes the call a candidate (we may have missed a pattern); an empty
    one holds none."""
    home = env.get("HOME") or os.path.expanduser("~")
    managed = env.get(MANAGED_ENV) or MANAGED_DIR
    # (path, machine-wide): only machine-wide files load in every session, so only they protect.
    files = [(os.path.join(home, ".claude", "settings.json"), True),
             (os.path.join(managed, "managed-settings.json"), True)]
    files += [(f, True) for f in sorted(glob.glob(os.path.join(managed, "managed-settings.d",
                                                               "*.json")))]
    project = env.get("CLAUDE_PROJECT_DIR")
    if project:
        files += [(os.path.join(project, ".claude", "settings.json"), False),
                  (os.path.join(project, ".claude", "settings.local.json"), False)]
    out = {"excludedCommands": [], "denyWrite": [], "allowWrite": [], "editDeny": []}
    errors = []
    for path, machine_wide in files:
        try:
            with open(path) as f:
                text = f.read()
            # An empty file is no settings to Claude Code: the sandbox's mount points for
            # protected files it lacks can stay behind as empty files on disk.
            data = json.loads(text) if text.strip() else {}
        except FileNotFoundError:
            continue
        except (OSError, ValueError, RecursionError) as e:   # json recurses on nesting
            errors.append(f"{path}: {type(e).__name__}")
            continue
        perms = data.get("permissions") if isinstance(data, dict) else None
        deny = perms.get("deny") if isinstance(perms, dict) else None
        if machine_wide and isinstance(deny, list):
            # `~` as Claude Code is likely to expand it: $HOME as given, so a symlinked home
            # fails Machine's no-symlink check rather than counting through the link.
            for parsed in (edit_rule_path(r, os.path.abspath(home)) for r in deny):
                if isinstance(parsed, str):
                    out["editDeny"].append(parsed)
        sandbox = data.get("sandbox") if isinstance(data, dict) else None
        if not isinstance(sandbox, dict):
            continue
        fs = sandbox.get("filesystem") if isinstance(sandbox.get("filesystem"), dict) else {}
        keys = [("excludedCommands", sandbox), ("allowWrite", fs)]
        if machine_wide:
            keys.append(("denyWrite", fs))
        for key, src in keys:
            values = src.get(key)
            if isinstance(values, list):
                out[key] += [v for v in values if isinstance(v, str)]
    out["denyWrite"] = [expand(p, home) for p in out["denyWrite"]]
    out["allowWrite"] = [expand(p, home) for p in out["allowWrite"]]
    return out, errors


# --- Matching ----------------------------------------------------------------------------------

def pattern_re(pattern):
    return re.compile("".join(".*" if part == "*" else re.escape(part)
                              for part in re.split(r"(\*)", pattern)), re.S)


def normalize(piece):
    """Strip leading `VAR=value` words and `(`, `{`, `!`, and a closing `)` or `}`."""
    s = piece.strip().rstrip(")} \t")
    while True:
        m = ASSIGN.match(s)
        if m:
            s = s[m.end():]
        elif s[:1] in ("(", "{", "!"):
            s = s[1:].lstrip()
        else:
            return s


def first_word(text):
    try:
        words = shlex.split(text)
    except ValueError:
        words = text.split()
    return words[0] if words else ""


def all_pieces(command):
    return [command.strip(), normalize(command)] + [normalize(p) for p in SPLIT.split(command)]


def matching_pieces(command, patterns):
    """Every piece (whole command first) an excludedCommands pattern matches."""
    regexes = [pattern_re(p) for p in patterns]
    return [p for p in all_pieces(command) if p and any(r.fullmatch(p) for r in regexes)]


def heads_of(pieces):
    heads = []
    for piece in pieces:
        head = first_word(normalize(piece))
        if head and head not in heads:
            heads.append(head)
    return heads


def candidates(command, patterns):
    """The heads of every matching piece (whole command first). Empty: not a candidate."""
    return heads_of(matching_pieces(command, patterns))


# --- Path arguments ----------------------------------------------------------------------------

# Rule 1 judges each path argument a head runs git in (itself or through a child) as it judges
# the cwd: pass-respawn -C (handoff-check runs git status there, then a claude starts there),
# lane adopt PATH, and a local repository for git push, fetch, pull and ls-remote (git runs the
# target's receive-pack or upload-pack). Left unjudged by design (docs/delegation.md): lane addr
# --repo, whose one git lookup there runs under lanelib.HANDED_ENV and starts no repo-local
# program, and codex-delegate run --dir, which the delegation skill sends to any repo.
PATH_HEADS = {"pass-respawn", "lane", "git", "delegation-ledger"}
GIT_PATH_SUBS = {"push", "fetch", "pull", "ls-remote"}
# Long options of those whose value is a program git runs (git takes any unique prefix), and
# ls-remote's short -u for --upload-pack; an `ext::` remote runs a command too.
GIT_PROGRAM_OPTIONS = ("receive-pack", "upload-pack", "exec")
# --recurse-submodules (any prefix git takes, and its -default form) runs git in each
# submodule's own gitdir, whose config the guard never judges; --no-recurse-submodules is fine.
GIT_RECURSE = "recurse-submodules"
# zsh's operators, longest first. A redirection takes the next word as its target; any other
# ends a piece.
CONTROL_OPS = (";;&", ";;", ";&", ";|", "&&", "||", "|&", "&|", "&!", ";", "&", "|", "\n")
REDIRECT_OPS = ("&>>|", "&>>!", ">>&|", ">>&!", "<<<", "<<-", "&>>", "&>|", "&>!", ">>|", ">>!",
                ">&|", ">&!", ">>&", "<<", ">>", "<>", ">|", ">!", ">&", "<&", "&>", "<", ">")
SHELL_OPS = sorted(CONTROL_OPS + REDIRECT_OPS, key=len, reverse=True)
WORD_END = " \t\n;&|<>)"
FD = re.compile(r"[0-9]+")  # ASCII only: str.isdigit() takes ² and other digits zsh doesn't
# Words after which the next word is in command position (a `{` there opens a group).
COMMAND_WORDS = {"{", "!", "if", "then", "else", "elif", "while", "until", "do", "time"}
# A word the shell hands on as typed: no expansion, glob, quote or space. `~` only as $HOME.
PLAIN_WORD = re.compile(r"(~(?=/|$))?[A-Za-z0-9_./:@%+,=-]*")


def path_arguments(words):
    """(path, existing_only) for each path argument in words, a piece's argv. Every spelling
    counts, every repeat too (argparse keeps the last; the guard judges all). git's repository
    words also name remotes and refs, so only a path that exists counts there."""
    head, args = os.path.basename(words[0]), words[1:]
    out = []
    if head == "pass-respawn":
        for i, w in enumerate(args):
            if w == "-C" and i + 1 < len(args):
                out.append(args[i + 1])
            elif w.startswith("-C") and w != "-C":
                # `-C=x` is x on Python 3.12 and `=x` on older ones: judge both.
                out += [w[2:]] + ([w[3:]] if w.startswith("-C=") else [])
        return [(p, False) for p in out]
    if head == "lane" and args[:1] == ["adopt"]:
        # Every word but its options; `--id`'s value is judged too (an over-match only adds checks).
        return [(w, False) for w in args[1:]
                if w not in ("--", "--id", "-h", "--help") and not w.startswith("--id=")]
    if head == "git" and args[:1] and args[0] in GIT_PATH_SUBS:
        for w in args[1:]:
            if w.startswith("-"):
                if "=" in w:
                    out.append(w.split("=", 1)[1])
            else:
                out.append(w)
        return [(p, True) for p in out]
    return []


class Op(str):
    """An operator outside quotes, as opposed to a word with the same text."""


class ShellLexer:
    """zsh's words and operators for a command, enough to find each call and its arguments.
    Quotes are removed; backslash-newline joins; a comment and a heredoc's body are skipped; a
    redirection's fd number is dropped. A `$(...)`, backtick, `<(...)`, `${...}`, `$'...'` or
    zsh glob group `(...)` stays in its word as a marker no plain word matches, and the commands
    inside (an unquoted heredoc's too) are lexed into `subs`, so their calls are judged as well.
    Raises ValueError where the text doesn't parse (an unclosed quote or substitution) and for
    what it doesn't read: arithmetic (`$((`, `((`, `$[`), a heredoc delimiter holding an
    expansion, and a heredoc with no end line."""

    def __init__(self, text):
        self.s, self.i, self.subs, self.heredocs = text, 0, [], []

    def peek(self, k=0):
        return self.s[self.i + k:self.i + k + 1]

    def nested(self):
        """Lex the command after a `(` up to its `)` into subs."""
        self.subs.append(self.command(nested=True))

    def command(self, nested=False):
        """The tokens up to the end, or with nested, up to the `)` closing a `(` already read."""
        out, cases, braces, delim_for = [], 0, 0, None
        while c := self.peek():
            if c in " \t" or c == "\\" and self.peek(1) == "\n":
                self.i += 1 if c != "\\" else 2
            elif c == "#":  # a word's first character: a comment
                while self.peek() not in ("", "\n"):
                    self.i += 1
            elif c == ")":
                self.i += 1
                if nested and not cases:
                    return out
                out.append(Op(";"))  # a case pattern's end, or a stray
            elif c == "(" or c in "<>" and self.peek(1) == "(":
                if c == "(" and self.peek(1) == "(":
                    raise ValueError("arithmetic, which the guard doesn't read")
                self.i += 1 if c == "(" else 2
                self.nested()
                out.append(f"{c if c != '(' else ''}(…)")
            elif op := next((o for o in SHELL_OPS if self.s.startswith(o, self.i)), None):
                self.i += len(op)
                out.append(Op(op))
                if op in ("<<", "<<-"):
                    delim_for = op
                elif op == "\n":
                    self.read_heredocs()
            else:
                at_command = not out or isinstance(out[-1], Op) or out[-1] in COMMAND_WORDS
                word, quoted = self.word()
                if delim_for:
                    if "…" in word:
                        raise ValueError("a heredoc delimiter holding an expansion")
                    self.heredocs.append((word, delim_for == "<<-", not quoted))
                    delim_for = None
                elif FD.fullmatch(word) and not quoted and self.peek() in ("<", ">"):
                    continue  # an fd number: 2>&1
                elif not quoted and word == "}" and braces:
                    braces -= 1
                    out.append(Op(";"))  # a group's end, even after arguments
                    continue
                out.append(word)
                if not quoted and word == "{" and at_command:
                    braces += 1
                elif not quoted and word == "case":
                    cases += 1
                elif not quoted and word == "esac" and cases:
                    cases -= 1
        if nested:
            raise ValueError("an unclosed `(`")
        return out

    def word(self):
        """(text, quoted) for the word at self.i."""
        parts, quoted = [], False
        while (c := self.peek()) and c not in WORD_END:
            n = self.peek(1)
            if c == "\\":
                if n != "\n":
                    parts.append(n or "\\")
                    quoted = True
                self.i += 2
            elif c == "'":
                end = self.s.find("'", self.i + 1)
                if end < 0:
                    raise ValueError("an unclosed '")
                parts.append(self.s[self.i + 1:end])
                self.i, quoted = end + 1, True
            elif c == '"':
                self.i += 1
                parts.append(self.expanded('"'))
                quoted = True
            elif c == "$" and n == "'":
                end = self.i + 2
                while end < len(self.s) and self.s[end] != "'":
                    end += 2 if self.s[end] == "\\" else 1
                if end >= len(self.s):
                    raise ValueError("an unclosed $'")
                parts.append("$'…'")
                self.i, quoted = end + 1, True
            elif c == "(":  # glued to the word: a zsh glob group
                if n == "(":
                    raise ValueError("arithmetic, which the guard doesn't read")
                self.i += 1
                self.nested()
                parts.append("(…)")
            elif marker := self.expansion():
                parts.append(marker)
            else:
                parts.append(c)
                self.i += 1
        return "".join(parts), quoted

    def expansion(self):
        """At a `$(`, `${` or backtick: lex it into subs and return its marker; else ""."""
        c, n = self.peek(), self.peek(1)
        if c == "$" and (n == "[" or n == "(" and self.peek(2) == "("):
            raise ValueError("arithmetic, which the guard doesn't read")
        if c == "$" and n == "(":
            self.i += 2
            self.nested()
            return "$(…)"
        if c == "$" and n == "{":
            self.i += 2
            depth = 0
            while (c := self.peek()) != "}" or depth:
                if not c or c in "'\"":
                    raise ValueError("a ${...} the guard can't read")
                if c == "\\":
                    self.i += 2
                elif not self.expansion():
                    depth += {"{": 1, "}": -1}.get(c, 0)
                    self.i += 1
            self.i += 1
            return "${…}"
        if c == "`":
            end, inner = self.i + 1, []
            while end < len(self.s) and self.s[end] != "`":
                if self.s[end] == "\\" and self.s[end + 1:end + 2] == "\n":
                    end += 2  # zsh joins the line before it reads the command inside
                    continue
                if self.s[end] == "\\" and self.s[end + 1:end + 2] in ("`", "\\", "$"):
                    end += 1
                inner.append(self.s[end:end + 1])
                end += 1
            if end >= len(self.s):
                raise ValueError("an unclosed `")
            sub = ShellLexer("".join(inner))
            self.subs += [sub.command()] + sub.subs
            self.i = end + 1
            return "`…`"
        return ""

    def expanded(self, end):
        """Text up to the unescaped `end` (consumed), or to the text's end with end None, read as
        inside double quotes: a backslash quotes $ ` " \\ and joins a newline."""
        parts = []
        while (c := self.peek()) != end:
            if not c:
                raise ValueError('an unclosed "')
            n = self.peek(1)
            if c == "\\":
                parts.append("" if n == "\n" else n if n in '$`"\\' else "\\" + n)
                self.i += 2
            elif marker := self.expansion():
                parts.append(marker)
            else:
                parts.append(c)
                self.i += 1
        self.i += 1
        return "".join(parts)

    def line(self):
        """The physical line at self.i, consumed with its newline."""
        nl = self.s.find("\n", self.i)
        end = len(self.s) if nl < 0 else nl
        line, self.i = self.s[self.i:end], end + (nl >= 0)
        return line

    def read_heredocs(self):
        """After a newline: skip each pending heredoc's body to its delimiter line, lexing an
        unquoted one's substitutions. In an unquoted one a backslash-newline joins lines before
        the delimiter is matched."""
        pending, self.heredocs = self.heredocs, []
        for delim, strip_tabs, expand in pending:
            start = self.i
            while True:
                if self.i >= len(self.s):
                    raise ValueError("a heredoc with no end line")
                body_end, line = self.i, self.line()
                while expand and (len(line) - len(line.rstrip("\\"))) % 2 and self.i < len(self.s):
                    line = line[:-1] + self.line()
                if (line.lstrip("\t") if strip_tabs else line) == delim:
                    break
            if expand:
                sub = ShellLexer(self.s[start:body_end])
                sub.expanded("")
                self.subs += sub.subs


def path_calls(command):
    """(argv, targets) for each call of a PATH_HEADS program, the way zsh splits the command
    (ShellLexer): in every piece between control operators, a substitution's too, each word
    naming one starts a call running to the piece's end (subshells, groups, `if`, `VAR=`
    prefixes and wrappers like `env` included), less the piece's redirections, whose targets
    are judged as plain words too (a `$(...)` there runs before git does)."""
    lexer = ShellLexer(command)
    streams = [lexer.command()] + lexer.subs
    for tokens in streams:
        pieces, words, targets, i = [], [], [], 0
        while i < len(tokens):
            t = tokens[i]
            i += 1
            if not isinstance(t, Op):
                words.append(t)
            elif t in REDIRECT_OPS:
                if i < len(tokens) and not isinstance(tokens[i], Op):
                    targets.append(tokens[i])
                    i += 1
            else:
                pieces.append((words, targets))
                words, targets = [], []
        pieces.append((words, targets))
        for words, targets in pieces:
            for i, w in enumerate(words):
                if os.path.basename(w) in PATH_HEADS:
                    yield words[i:], targets


def check_calls(m, env, cwd, project, command):
    """Rule 1 for the path arguments of every PATH_HEADS call in the command."""
    try:
        calls = list(path_calls(command))
    except ValueError as e:
        raise Refusal("rule1", "(command)", f"the guard can't read this command as zsh would "
                      f"({e}), so it can't find the path arguments in it. Run it as plain "
                      "commands.")
    for words, targets in calls:
        check_path_arguments(m, env, cwd, project, words, targets)


def check_path_arguments(m, env, cwd, project, words, targets):
    """Rule 1 for each path argument of one call (path_arguments), resolved from cwd."""
    head = os.path.basename(words[0])
    sub = next((w for w in words[1:] if not w.startswith("-")), None)
    if head == "git" and words[1:2] and words[1].startswith("-") and any(
            w in GIT_PATH_SUBS for w in words[2:]):
        raise Refusal("rule1", words[1], f"`git` with {words[1]!r} before its subcommand: the "
                      "guard judges git push, fetch, pull and ls-remote only with no git option "
                      "before the subcommand. Run it from the repository's directory without "
                      "that option.")
    if head == "delegation-ledger":
        if sub == "hook":
            raise Refusal("rule1", head, "`delegation-ledger hook` reads the checkout it runs "
                          "git in from its stdin, which the guard can't judge. Claude Code's "
                          "hooks run it directly, never through Bash.")
        return
    if head == "lane" and sub != "adopt" or head == "git" and sub not in GIT_PATH_SUBS:
        return
    name = head if head == "pass-respawn" else f"{head} {sub}"
    for w in words[1:] + targets:
        # git %-decodes a file:// URL's path, so a `%` could spell any path.
        if not PLAIN_WORD.fullmatch(w) or w.startswith("=") or head == "git" and "%" in w:
            raise Refusal("rule1", w, f"`{name}` takes a path argument, and {w!r} is not a plain "
                          "word (an expansion, glob, quote, space or %-escape that would be "
                          "rewritten before git sees it). Spell paths and refs as plain words.")
    if head == "git":
        check_git_words(sub, words[2:], discover(cwd, env))
    for path, existing_only in path_arguments(words):
        if existing_only and path.startswith("file://"):
            path = path[len("file://"):]
            if not path.startswith("/"):  # git drops a host part: judge no guess at the rest
                raise Refusal("rule1", path, f"`git {sub}` names a file:// URL with a host part "
                              f"(file://{path}); give the repository as a plain path.")
        full = os.path.join(cwd, os.path.expanduser(path))
        if not existing_only:
            check_rule1(m, env, full, project, arg=path)
            continue
        # git's server side tries <path> and then <path>.git, and reads a file there as a
        # gitfile; a dir it judges as rule 1 judges the cwd (which also finds <dir>/.git).
        for found in (full, full + ".git"):
            if os.path.isfile(found):
                try:
                    found = read_gitfile(found)
                except Exception:
                    continue  # no gitfile (a bundle, say): git reads no config from it
            if os.path.lexists(found):
                check_rule1(m, env, found, project, arg=path)


def check_git_words(sub, args, repo):
    """Refuse a git push, fetch, pull or ls-remote word naming what rule 1 can't judge: a program
    for git to run (an option of GIT_PROGRAM_OPTIONS by any prefix, ls-remote's -u, an ext::
    remote, also as an option's value), submodule recursion, or a remote defined by a legacy
    file in the project's git dir (.git/remotes, .git/branches: outside the judged config)."""
    for w in args:
        name = w[2:].split("=", 1)[0] if w.startswith("--") else ""
        value = w.split("=", 1)[1] if name and "=" in w else w
        if (name and any(o.startswith(name) for o in GIT_PROGRAM_OPTIONS)
                or sub == "ls-remote" and re.match(r"-[^-]*u", w) or value.startswith("ext::")):
            raise Refusal("rule1", w, f"`git {sub}` with {w!r} names a program for git to run "
                          "outside the sandbox, which the guard can't judge. Run it without that "
                          "option.")
        if (len(name) >= 4 and (GIT_RECURSE.startswith(name) or name.startswith(GIT_RECURSE))
                and value not in ("no", "false")):
            raise Refusal("rule1", w, f"`git {sub}` with {w!r} runs git in each submodule's "
                          "own git dir, whose config the guard doesn't judge. Run it without "
                          "submodule recursion.")
        # The repository word: a positional, or --repo's value (git takes a prefix of it).
        # git takes it as a remote's nick only with no `/` and not `.` or `..`.
        nick = (value if len(name) >= 3 and "repo".startswith(name) and "=" in w
                else None if w.startswith("-") else w)
        if repo and nick and "/" not in nick and nick not in (".", "..") and any(
                os.path.lexists(os.path.join(repo[1], kind, nick))
                for kind in ("remotes", "branches")):
            raise Refusal("rule1", w, f"`git {sub}` names {nick!r}, a remote a legacy file in the "
                          f"project's git dir ({repo[1]}/remotes or /branches) defines, outside "
                          "the config the guard judges. Define it in .git/config instead.")


# --- Machine view ------------------------------------------------------------------------------

def under(path, root):
    root = root.rstrip("/") or "/"
    return path == root or path.startswith(root if root == "/" else root + "/")


class Machine:
    def __init__(self, env, settings, cwd):
        self.env = env
        self.home = os.path.realpath(env.get("HOME") or os.path.expanduser("~"))
        self.cwd = cwd
        roots = [self.home, "/tmp"] + ([env["TMPDIR"]] if env.get("TMPDIR") else [])
        roots += settings["allowWrite"]
        self.roots = [os.path.realpath(r) for r in roots]
        # An Edit deny rule binds sandboxed Bash and the Edit/Write tools; a denyWrite line binds
        # Bash only, so it protects only inside dotclaude's own checkouts (this guard's, and
        # ~/dotclaude), whose hooks run outside the sandbox on every call anyway.
        own = [os.path.realpath(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                             os.pardir)),
               os.path.realpath(os.path.join(self.home, "dotclaude"))]
        sandbox_only = [
            d for d in settings["denyWrite"]
            if any(under(os.path.abspath(d), o) or under(os.path.realpath(d), o) for o in own)]
        # An Edit rule counts at its own path only, and only when no symlink sits along it: what
        # a rule through a link binds wasn't probed, and a link's target can change.
        self.deny = ([os.path.abspath(d) for d in settings["editDeny"]
                      if os.path.realpath(d) == os.path.abspath(d)]
                     + [os.path.abspath(d) for d in sandbox_only]
                     + [os.path.realpath(d) for d in sandbox_only]
                     + [self.resolved(os.path.abspath(d)) for d in sandbox_only]
                     + [os.path.join(self.home, ".claude")])
        self.gitconfig = os.path.join(self.home, ".gitconfig")
        # exposed() and chain() by path: every head walks the same PATH entries, and an lstat
        # on a /mnt/c entry (WSL's 9p) costs about a millisecond. Valid while deny stands.
        self.memo = {}

    def protect(self, d):
        """Judge on as if `d` were protected: all_refusals puts a refusal's fix in place. More
        protection can only clear a verdict, so the clean ones stand and every verdict that
        found something exposed is judged again: the memo then holds what a fresh Machine with
        this deny list would find."""
        self.deny.append(d)
        self.memo = {k: v for k, v in self.memo.items()
                     if v is None or (isinstance(v, tuple) and v[0] == "ok")}

    def resolved(self, p):
        """Realpath, but a symlink itself stays itself (it can be replaced by its dir's owner)."""
        if os.path.islink(p):
            return os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))
        return os.path.realpath(p)

    def always_protected(self, p):
        """~/.gitconfig as a regular file at that exact path: Claude Code protects the name in
        every session. A symlink there is judged by its hops and target instead."""
        return p == self.gitconfig and not os.path.islink(p) and os.path.isfile(p)

    def writable(self, path):
        """Writable in the machine view: the path, or its nearest existing ancestor (at that
        ancestor's target when it is a symlink), sits under a root, no denyWrite entry or always-protected path covers it, and some component from it
        up to its root is the user's own or writable by the user (an owner can chmod it back, a
        writable parent can rename it). Permission bits alone protect nothing inside a root."""
        p = os.path.abspath(os.path.join(self.cwd, path))
        q = p
        while not os.path.lexists(q):
            q = os.path.dirname(q)
        # A missing tail under a symlinked q gets created in q's target, so judge it there; the
        # link itself is judged as an ancestor by exposed() and chain().
        real = os.path.realpath(q) if q != p and os.path.islink(q) else self.resolved(q)
        if not any(under(real, r) for r in self.roots):
            return False
        if self.always_protected(q):
            return False
        # Resolved only: a path reached through a symlink in a denied dir is not in that dir.
        # The missing tail has no symlinks, so a denied name that doesn't exist yet still counts.
        full = os.path.normpath(os.path.join(real, os.path.relpath(p, q)))
        if any(under(full, d) for d in self.deny):
            return False
        uid = os.getuid()
        c = real
        while any(under(c, r) for r in self.roots):
            try:
                st = os.lstat(c)
            except OSError:
                return True  # can't tell: count it writable
            if st.st_uid == uid or (not os.path.islink(c) and os.access(c, os.W_OK)):
                return True
            if c == "/":
                break
            c = os.path.dirname(c)
        return False

    def exposed(self, path):
        """The first writable thing along `path` (a symlinked ancestor, then the path), or None."""
        p = os.path.abspath(os.path.join(self.cwd, path))
        if ("exposed", p) not in self.memo:
            self.memo["exposed", p] = self._exposed(p)
        return self.memo["exposed", p]

    def _exposed(self, p):
        parts = p.strip("/").split("/")
        for i in range(1, len(parts)):
            a = "/" + "/".join(parts[:i])
            if os.path.islink(a) and self.writable(a):
                return a
        return p if self.writable(p) else None

    def chain(self, path, rule, refuse):
        """Follow `path`'s symlink chain, raising `refuse(bad)` for the first hop, or dir of a
        hop, that is exposed. Returns the final target. Rules 1 and 2 both judge files this way."""
        p = os.path.abspath(os.path.join(self.cwd, path))
        if ("chain", p) not in self.memo:
            self.memo["chain", p] = self._chain(p)
        kind, at = self.memo["chain", p]
        if kind == "bad":
            raise refuse(at)
        if kind == "loop":
            raise Refusal(rule, at, f"{path} has a symlink loop at {at}; could not verify it.")
        return at

    def _chain(self, p):
        """("ok", final target), ("bad", the exposed path) or ("loop", where it gave up)."""
        for _ in range(40):
            if self.always_protected(p):
                return "ok", p
            # A file or symlink is replaced by whoever writes its dir; a real dir stands on its
            # own, as a PATH entry does.
            real_dir = os.path.isdir(p) and not os.path.islink(p)
            for x in (p,) if real_dir else (p, os.path.dirname(p)):
                bad = self.exposed(x)
                if bad:
                    return "bad", bad
            if not os.path.islink(p):
                return "ok", p
            p = os.path.normpath(os.path.join(os.path.dirname(p), os.readlink(p)))
        return "loop", p


# --- Rule 1: git config ------------------------------------------------------------------------

def gitdir_info(gitdir, at_root=False):
    """(gitdir, common) from git's real layout, never from a pointer alone. A gitdir with no
    `commondir` file is its own common dir. One with a `commondir` file must be a linked
    worktree's: it sits at `<common>/worktrees/<name>`, its `commondir` resolves to that
    `<common>`, and `<common>` holds no `commondir` of its own. `at_root` marks a `<top>/.git`
    dir, which is never a linked gitdir. Any break refuses: the main `.git/` is writable from a
    sandboxed session, so a planted `commondir` there must not pick which common dir is trusted.
    This leans on Claude Code protecting the session's own gitfile and its
    `worktrees/<name>/commondir`."""
    gitdir = os.path.realpath(gitdir)
    pointer = os.path.join(gitdir, "commondir")
    if not os.path.lexists(pointer):
        return gitdir, gitdir
    with open(pointer) as f:
        common = os.path.realpath(os.path.join(gitdir, f.read().strip()))
    parent = os.path.dirname(gitdir)
    if (at_root or os.path.basename(parent) != "worktrees"
            or common != os.path.dirname(parent)
            or os.path.lexists(os.path.join(common, "commondir"))):
        raise Refusal("rule1", gitdir, f"the git dir {gitdir} has an unexpected layout; refusing "
                      "an excluded command.")
    return gitdir, common


def read_gitfile(path):
    with open(path) as f:
        line = f.readline().strip()
    if not line.startswith("gitdir:"):
        raise ValueError(f"invalid gitfile {path}")
    target = line[len("gitdir:"):].strip()
    return os.path.join(os.path.dirname(path), target)


def looks_like_gitdir(d):
    """A dir git takes as a repo itself: HEAD, plus objects/ and refs/ here or a commondir (git
    then looks for them in the dir it names). Broader than git, never narrower: a dir counted
    here meets gitdir_info's layout check."""
    if not os.path.lexists(os.path.join(d, "HEAD")):
        return False
    return os.path.lexists(os.path.join(d, "commondir")) or (
        os.path.isdir(os.path.join(d, "objects")) and os.path.isdir(os.path.join(d, "refs")))


def discover(start, env=None):
    """(gitdir, common, top) for the repo git would use from `start`, or None."""
    env = env or {}
    start = os.path.realpath(start)
    if env.get("GIT_DIR"):
        gitdir, common = gitdir_info(os.path.join(start, env["GIT_DIR"]))
        top = env.get("GIT_WORK_TREE") or start
        return gitdir, common, os.path.realpath(os.path.join(start, top))
    ceilings = {os.path.realpath(c) for c in (env.get("GIT_CEILING_DIRECTORIES") or "").split(":")
                if c}
    d = start
    while True:
        dotgit = os.path.join(d, ".git")
        if os.path.isdir(dotgit):
            return gitdir_info(dotgit, at_root=True) + (d,)
        if os.path.isfile(dotgit):
            return gitdir_info(read_gitfile(dotgit)) + (d,)
        if looks_like_gitdir(d):
            return gitdir_info(d) + (d,)
        parent = os.path.dirname(d)
        if parent == d or parent in ceilings:
            return None
        d = parent


def parse_value(raw):
    out, quoted, i = [], False, 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            out.append({"n": "\n", "t": "\t", "b": "\b"}.get(raw[i + 1], raw[i + 1]))
            i += 2
            continue
        if c == '"':
            quoted = not quoted
        elif c in "#;" and not quoted:
            break
        else:
            out.append(c)
        i += 1
    return "".join(out).strip()


def config_entries(path):
    """(section, key, value) for each `key = value` in a git config file. Section is lowercased
    and its subsection dropped: `[includeIf "gitdir:x"]` reads as `includeif`."""
    with open(path, errors="replace") as f:
        text = f.read().replace("\\\n", "")
    section = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            end = line.find("]")
            if end < 0:
                continue
            header = line[1:end].strip()
            section = re.split(r'[\s."]', header, 1)[0].lower()
            line = line[end + 1:].strip()
        if not line or line[0] in "#;":
            continue
        key, eq, value = line.partition("=")
        key = key.strip().lower()
        yield section, key, parse_value(value) if eq else "true"


def config_refs(path, home):
    """Include targets and core.hooksPath values named in one config file."""
    includes, hooks = [], []
    for section, key, value in config_entries(path):
        if not value:
            continue
        if section in ("include", "includeif") and key == "path":
            v = expand(value, home)
            includes.append(os.path.join(os.path.dirname(path), v))
        elif section == "core" and key == "hookspath":
            hooks.append(expand(value, home))
    return includes, hooks


def check_rule1(m, env, cwd, project, arg=None):
    """Rule 1 for the repo at cwd: the call's own cwd, or the path argument arg resolved to
    cwd (check_path_arguments)."""
    repo = discover(cwd, env)
    proj = discover(project, {k: env[k] for k in ("GIT_CEILING_DIRECTORIES",) if k in env})
    if repo and (proj is None or repo[1] != proj[1]):
        what, fix = ((f"the path argument {arg}", "Name a path in the project's repository")
                     if arg is not None else
                     ("the working directory", "Run it from the project's repository"))
        raise Refusal("rule1", repo[0],
                      f"{what} is in the repository with git dir {repo[0]}, not the project's. "
                      f"{fix}, or run it from a session launched in that repository.")
    home = m.home
    trusted, files = [], []
    if repo:
        gitdir, common, top = repo
        # Claude Code protects the session's own gitdir, so config.worktree is trusted only there.
        trusted = [os.path.join(common, "config")]
        worktree_cfg = os.path.join(gitdir, "config.worktree")
        (trusted if gitdir == proj[0] else files).append(worktree_cfg)
    if env.get("GIT_CONFIG_GLOBAL"):
        files.append(expand(env["GIT_CONFIG_GLOBAL"], home))
    else:
        files.append(os.path.join(home, ".gitconfig"))
        xdg = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        files.append(os.path.join(xdg, "git", "config"))
    if not env.get("GIT_CONFIG_NOSYSTEM") or env["GIT_CONFIG_NOSYSTEM"].lower() in ("0", "false",
                                                                                   "no", "off"):
        files.append(env.get("GIT_CONFIG_SYSTEM") or "/etc/gitconfig")
    seen = set()
    queue = [(f, True, 0) for f in trusted] + [(f, False, 0) for f in files]
    hooks_base = repo[2] if repo else cwd
    while queue:
        path, is_trusted, depth = queue.pop(0)
        path = os.path.abspath(os.path.join(cwd, path))
        if path in seen or not os.path.lexists(path):
            continue
        seen.add(path)
        target = path
        if not is_trusted:
            target = m.chain(path, "rule1", lambda bad, path=path: Refusal(
                "rule1", bad, f"git reads the config file {path}, which a sandboxed session can "
                f"write ({bad}).", protect=m))
        if not os.path.isfile(target):
            continue  # judged above; only a regular file is parsed
        includes, hooks = config_refs(target, home)
        if depth < INCLUDE_DEPTH:
            queue += [(i, False, depth + 1) for i in includes]
        for h in hooks:
            check_hooks_dir(m, os.path.join(hooks_base, h))


def check_hooks_dir(m, hdir):
    def refuse(bad):
        return Refusal("rule1", bad, f"core.hooksPath points at {hdir}, which a sandboxed "
                       f"session can write ({bad}); a repo's install step (husky and similar) "
                       "often sets it.", protect=m)
    if not os.path.lexists(hdir):
        bad = m.exposed(hdir)
        if bad:
            raise refuse(bad)
        return
    target = m.chain(hdir, "rule1", refuse)
    if os.path.isdir(target):
        for name in sorted(os.listdir(target)):
            m.chain(os.path.join(target, name), "rule1", refuse)


# --- Rule 2: PATH ------------------------------------------------------------------------------

def path_refusal(head, path, m):
    return Refusal("rule2", path, f"`{head}` resolves through {path}, which a sandboxed session "
                   "can write. Drop it from PATH, or protect it.", protect=m)


def which(m, head, path_var, label, depth):
    """Find `head` on PATH. Every entry must be protected, not only those searched before it:
    the head's children (git, gh, tmux, the tools claude spawns) search the same PATH."""
    found = None
    for entry in path_var.split(":"):
        if not entry or not os.path.isabs(entry):
            raise Refusal("rule2", entry or "(empty)",
                          f"PATH holds {entry or 'an empty entry'!r}, which searches the working "
                          f"directory for `{label}`. Drop it from PATH.")
        if os.path.lexists(entry):
            m.chain(entry, "rule2", lambda bad: path_refusal(label, bad, m))
        else:
            bad = m.exposed(entry)
            if bad:
                raise path_refusal(label, bad, m)
        cand = os.path.join(entry, head)
        if found is None and os.path.isfile(cand) and os.access(cand, os.X_OK):
            found = cand
    if found:
        check_file(m, found, path_var, label, depth)


def check_file(m, path, path_var, label, depth):
    if depth > SHEBANG_DEPTH:
        raise Refusal("rule2", path, f"`{label}` runs through more than {SHEBANG_DEPTH} "
                      "interpreters; could not verify it.")
    p = m.chain(path, "rule2", lambda bad: path_refusal(label, bad, m))
    try:
        # Never waiting on a FIFO: judging on past a refusal reaches files in writable dirs.
        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as f:
            if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                return  # no regular file: it can't run as a script
            line = f.readline(512)
    except OSError:
        return  # unreadable: it can't run as a script
    if not line.startswith(b"#!"):
        return
    words = line[2:].decode(errors="replace").split()
    if not words:
        return
    interp, args = words[0], words[1:]
    check_file(m, interp, path_var, label, depth + 1)
    if os.path.basename(interp) == "env":
        rest = []
        for a in args:
            rest += a.split() if a.startswith("-S") else [a]
        prog = next((a for a in rest if not a.startswith("-") and "=" not in a), None)
        if prog:
            if "/" in prog:
                check_file(m, prog, path_var, label, depth + 1)
            else:
                which(m, prog, path_var, label, depth + 1)


def check_rule2(m, head, path_var):
    if "/" in head:
        p = os.path.join(m.cwd, head)
        if os.path.lexists(p):
            check_file(m, p, path_var, head, 0)
        else:
            bad = m.exposed(p)
            if bad:
                raise path_refusal(head, bad, m)
    else:
        which(m, head, path_var, head, 0)


# --- Rule 3 and the verdict --------------------------------------------------------------------

def check_rule3(head, cwd, project):
    if os.path.basename(head) in PROJECT_HEADS and \
            os.path.realpath(cwd) != os.path.realpath(project):
        raise Refusal("rule3", cwd, f"`{os.path.basename(head)}` reads the working directory's "
                      f"project config, and {cwd} is not the project root. Run claude/codex from "
                      "the project root.")


def judge(heads, cwd, env, settings, command=""):
    project = env.get("CLAUDE_PROJECT_DIR")
    if not project:
        raise Refusal("project", "(unset)", "CLAUDE_PROJECT_DIR is unset, so the guard can't tell "
                      "the project's repository; refusing an excluded command.")
    m = Machine(env, settings, cwd)
    check_rule1(m, env, cwd, project)
    check_calls(m, env, cwd, project, command)
    for head in heads:
        check_rule2(m, head, env.get("PATH", ""))
        check_rule3(head, cwd, project)


# --- Every refusal ----------------------------------------------------------------------------------

def all_refusals(check, m, entries=None):
    """Every refusal `check(m)` gives in turn, so one run lists every rule: after each, judge on
    as if its fix were in place (its dir added to m.deny, or its empty or relative entry dropped
    from `entries`, the PATH list `check` reads) until the check passes or a refusal can't be
    cleared. Returns (refusals, the error that stopped it or None)."""
    found = []
    while True:
        try:
            check(m)
            return found, None
        except Refusal as r:
            found.append(r)
            bad = "" if r.path == "(empty)" else r.path
            if r.fix_dir and r.fix_dir not in m.deny:
                m.protect(r.fix_dir)
            elif entries is not None and bad in entries and not os.path.isabs(bad):
                entries.remove(bad)
            else:
                return found, None
        except Exception as e:
            return found, e


def project_refusals(env, cwd, project=None):
    """What rule 1 refuses for an excluded call from `cwd` in a session rooted at `project` (by
    default `cwd` itself: a lane's own session), every one: (refusals, error or None)."""
    project = project or cwd
    env = dict(env, CLAUDE_PROJECT_DIR=project)
    settings, _ = load_settings(env)
    return all_refusals(lambda m: check_rule1(m, env, cwd, project),
                        Machine(env, settings, cwd))


def path_refusals(m, heads, path_var):
    """What rule 2 refuses for each head on the full PATH, as the hook runs it, every one:
    (refusals, errors). One Machine for all heads, so a dir is listed once."""
    found, errors, entries = [], [], path_var.split(":")
    for head in heads:
        refusals, error = all_refusals(lambda m, head=head: check_rule2(m, head, ":".join(entries)),
                                       m, entries)
        # One that can't be cleared stops every head at the same place: list it once.
        found += [r for r in refusals if (r.rule, r.path) not in {(f.rule, f.path) for f in found}]
        if error:
            errors.append(error)
    return found, errors


def excluded_heads(settings):
    return sorted({first_word(normalize(p)) for p in settings["excludedCommands"]} - {""})


# An Edit rule's path, read looser than EDIT_RULE: its glob tail is cut back to a whole dir,
# since a rule over a removed dir names nothing whatever its form.
EDIT_ANY = re.compile(r"Edit\((//|~/)([^)]*)\)")


def rules_naming(path, env):
    """(settings file, rule) for each Edit deny rule inside `path` in the machine overlay
    (~/.claude/settings.machine.json, which dotclaude's setup.sh merges into settings.json),
    the user's settings.json and the managed files, in that order. `lane done` prints them for
    a closed lane's worktree: the guard reads no glob, so a lane's dir gets a rule of its own
    (a relative core.hooksPath), and closing the lane leaves that rule naming nothing. A file
    that can't be read is skipped."""
    home = env.get("HOME") or os.path.expanduser("~")
    managed = env.get(MANAGED_ENV) or MANAGED_DIR
    files = [os.path.join(home, ".claude", "settings.machine.json"),
             os.path.join(home, ".claude", "settings.json"),
             os.path.join(managed, "managed-settings.json")]
    files += sorted(glob.glob(os.path.join(managed, "managed-settings.d", "*.json")))
    targets = {os.path.abspath(path), os.path.realpath(path)}
    out = []
    for f in files:
        try:
            with open(f) as fh:
                text = fh.read()
            data = json.loads(text) if text.strip() else {}
        except (OSError, ValueError, RecursionError):   # json recurses on nesting
            continue
        perms = data.get("permissions") if isinstance(data, dict) else None
        deny = perms.get("deny") if isinstance(perms, dict) else None
        for rule in deny if isinstance(deny, list) else []:
            m = EDIT_ANY.fullmatch(rule) if isinstance(rule, str) else None
            if not m:
                continue
            # The literal dirs before the first glob. A glob mid-name (`lanes/x*/**`) widens to
            # its parent dir, which covers sibling lanes too, so such a rule never reads as inside.
            rest = m.group(2)
            g = re.search(r"[*?\[]", rest)
            literal = rest[:rest.rfind("/", 0, g.start()) + 1] if g else rest
            d = os.path.normpath(("/" if m.group(1) == "//" else home.rstrip("/") + "/")
                                 + literal)
            if any(under(p, t) for p in (d, os.path.realpath(d)) for t in targets):
                out.append((f, rule))
    return out


# --- Scan ----------------------------------------------------------------------------------------

SCAN_DEPTH = 4
SYSTEM_GITS = ("/usr/bin/git", "/usr/local/bin/git", "/opt/homebrew/bin/git")


def repos_under(root, depth=SCAN_DEPTH):
    """Dirs holding a .git entry, `root` and `depth` levels below it. Hidden dirs, node_modules
    and symlinks are not walked: no session is rooted there, and a link can loop."""
    found = []

    def walk(d, left):
        if os.path.lexists(os.path.join(d, ".git")):
            found.append(d)
        if left == 0:
            return
        try:
            names = sorted(os.listdir(d))
        except OSError:
            return
        for name in names:
            p = os.path.join(d, name)
            if name.startswith(".") or name == "node_modules" or os.path.islink(p) \
                    or not os.path.isdir(p):
                continue
            walk(p, left - 1)

    walk(os.path.abspath(root), depth)
    return found


def scan(roots, env):
    """What judge() would refuse for an excluded call from each repo's root: rule 2 once per
    excluded head, rule 1 per repo. Only machine-wide settings load, as for any project.
    One run lists what the next would, so a single paste clears PATH. Returns
    [(where, Refusal)], [(where, error)] for what it couldn't check, and the settings errors."""
    env = {k: v for k, v in env.items() if k != "CLAUDE_PROJECT_DIR"}
    settings, errors = load_settings(env)
    heads = excluded_heads(settings)
    found, unchecked = [], []
    cwd = env.get("HOME") or os.getcwd()
    m = Machine(env, settings, cwd)
    # Each entry on its own names every writable one.
    path_var = env.get("PATH", "")
    for p in path_var.split(":"):
        for head in heads:
            try:
                check_rule2(m, head, p)
            except Refusal as r:
                found.append(("PATH", r))
            except Exception as e:
                unchecked.append((p or "(empty PATH entry)", e))
    # The full PATH, as the hook runs it, catches an interpreter one entry's head resolves
    # through another.
    refusals, path_errors = path_refusals(Machine(env, settings, cwd), heads, path_var)
    found += [("PATH", r) for r in refusals]
    unchecked += [("PATH", e) for e in path_errors]
    for root in roots:
        for repo in repos_under(root):
            refusals, error = all_refusals(lambda m, repo=repo: check_rule1(m, env, repo, repo),
                                           Machine(env, settings, repo))
            found += [(repo, r) for r in refusals]
            if error:
                unchecked.append((repo, error))
    return found, unchecked, errors


def git_read(cwd, *args):
    """A git command that reads objects only. The scan runs outside the sandbox in repos whose
    config it hasn't judged, so it runs no command a config can attach a program to (status
    runs fsmonitor and filters, diff runs drivers), and skips the global and system config."""
    # A system git only: PATH's may be one the scan just found writable. No transport, so a
    # partial clone can't fetch a missing object through a program its config names.
    git = next((g for g in SYSTEM_GITS if os.path.isfile(g)), None)
    if not git:
        return None
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0",
               GIT_ALLOW_PROTOCOL="none", GIT_NO_LAZY_FETCH="1")
    try:
        p = subprocess.run([git, "--no-pager", *args], cwd=cwd, env=env, capture_output=True,
                           text=True, errors="surrogateescape", timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


def evidence(path, limit=12):
    """What `path` holds now, newest first, so its rule follows a look rather than a stamp: each
    entry's mtime and, inside a repo, whether it matches HEAD."""
    if not os.path.lexists(path):
        return ["    (missing: nothing there yet)"]
    d = path if os.path.isdir(path) else os.path.dirname(path)
    names = sorted(os.listdir(d)) if d == path else [os.path.basename(path)]
    top = (git_read(d, "rev-parse", "--show-toplevel") or "").strip()
    head = {}
    if top:
        for entry in (git_read(top, "ls-tree", "-r", "-z", "HEAD", "--",
                               os.path.relpath(d, top)) or "").split("\0"):
            meta, _, name = entry.partition("\t")
            if name:
                head[os.path.join(top, name)] = meta.split()[-1]
    rows = []
    for name in names:
        p = os.path.join(d, name)
        try:
            st = os.lstat(p)
        except OSError:
            continue
        state = ""
        if top and not stat.S_ISDIR(st.st_mode):  # ls-tree -r lists blobs, not dirs
            oid = head.get(p)
            if oid is None:
                state = "  not in HEAD"
            elif stat.S_ISREG(st.st_mode):
                with open(p, "rb") as f:
                    data = f.read()
                blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
                state = "  same as HEAD" if blob == oid else "  differs from HEAD"
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
        kind = "/" if stat.S_ISDIR(st.st_mode) else "@" if stat.S_ISLNK(st.st_mode) else ""
        rows.append((st.st_mtime, f"    {when}  {name}{kind}{state}"))
    rows.sort(reverse=True)
    lines = [r for _, r in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"    ... and {len(rows) - limit} older")
    return lines or ["    (empty)"]


def run_scan(roots):
    """Print each refusal once per path with what the path holds now, then settings.machine.json
    with the Edit deny rules that would clear them. Exits 1 when anything would be refused."""
    home = os.path.expanduser("~")
    found, unchecked, errors = scan(roots or [home], os.environ)
    for e in errors:
        print(f"settings not read: {e}")
    for line in dict.fromkeys(f"{w}: could not check ({type(e).__name__}: {e})"
                              for w, e in unchecked):
        print(line)
    first = {}
    for where, r in found:
        first.setdefault(r.path, (where, r))
    rules = []
    for where, r in first.values():
        print(f"{where}: excluded-guard ({r.rule}): {r.reason}")
        if r.fix:
            print(f"  {r.fix_dir} holds, before you protect it:")
            try:
                print("\n".join(evidence(r.fix_dir)))
            except Exception as e:
                print(f"    (could not read it: {type(e).__name__}: {e})")
            if r.fix not in rules:
                rules.append(r.fix)
    if rules:
        print_paste(os.path.join(home, ".claude", "settings.machine.json"), rules)
    if not (first or unchecked or errors):
        return 0
    print(f"Then {RERUN}.")  # last, where setup.sh's warning points
    return 1


def print_paste(machine, rules):
    """Print machine with the rules added to its permissions.deny, ready to paste; or, when it
    can't be read or has no usable deny list, the rules to add by hand."""
    try:
        with open(machine) as f:
            text = f.read()
        data = json.loads(text) if text.strip() else {}
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError, RecursionError) as e:   # json recurses on nesting
        print(f"{machine} not read ({type(e).__name__}); add these to its permissions.deny:")
        print("\n".join(f"  {json.dumps(r)}," for r in rules))
        return
    perms = data.setdefault("permissions", {}) if isinstance(data, dict) else None
    deny = perms.setdefault("deny", []) if isinstance(perms, dict) else None
    if not isinstance(deny, list):
        print(f"{machine} has no usable permissions.deny; add these to it:")
        print("\n".join(f"  {json.dumps(r)}," for r in rules))
        return
    deny += [r for r in rules if r not in deny]
    print(f"After a look at each dir above, {machine} with the rules added:")
    print(json.dumps(data, indent=2))


# --- SessionStart check (hooks/excluded-check.sh) ----------------------------------------------

SESSION_STATE = "excluded-check.json"
MACHINE_KEY = "machine"
MACHINE_KEYS = 8  # PATH keys kept: a PATH a tab started with, or that PATH and a project


def finding(r):
    return f"{r.path}: add {r.fix}" if r.fix else r.reason


def session_findings(env, project):
    """{key: [line]}: what the live guard would refuse an excluded call from the project's root
    (rule 3 aside: only a call's cwd decides it). PATH judged with the machine-wide settings
    alone is what every session shares: keyed MACHINE_KEY plus the PATH's hash, it shows once
    across projects and lanes, and a tab with another PATH gets its own key. What the project's
    own settings add to that (heads, write roots) and its git config are keyed by the project's
    path: its repo names its own includes and hooks dir, and each worktree has its own."""
    shared_env = {k: v for k, v in env.items() if k != "CLAUDE_PROJECT_DIR"}
    env = dict(env, CLAUDE_PROJECT_DIR=project)
    path_var = env.get("PATH", "")
    shared, unread = load_settings(shared_env)
    settings, _ = load_settings(env)

    def path_lines(s):
        refusals, errors = path_refusals(Machine(env, s, project), excluded_heads(s), path_var)
        return [finding(r) for r in refusals] + [
            f"PATH: could not check ({type(e).__name__}: {e})" for e in errors]

    # An unread project file only widens what the guard judges. An unread user or managed file
    # also takes its deny rules with it, so the guard may refuse what they would clear.
    machine = [f"settings not read: {e}: the guard misses its rules and patterns" for e in unread]
    machine += path_lines(shared)
    key = f"{MACHINE_KEY}:{hashlib.sha256(path_var.encode()).hexdigest()[:16]}"
    out = {key: machine}
    if any(settings[k] != shared[k] for k in ("excludedCommands", "allowWrite")):
        # PATH too decides these, so they go under this PATH's key for this project.
        out[f"{key}:{project}"] = [line for line in path_lines(settings) if line not in machine]
    refusals, error = all_refusals(lambda m: check_rule1(m, env, project, project),
                                   Machine(env, settings, project))
    mine = [finding(r) for r in refusals]
    if error:
        mine.append(f"its git config: could not check ({type(error).__name__}: {error})")
    out[project] = mine
    return out


def unseen(findings):
    """The findings whose key changed since the last start that showed them, and store the new
    ones. A key going to none is dropped, never shown. State that can't be read counts as none
    seen and one that can't be written is logged: a finding then shows at every start rather
    than never."""
    d = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                     "dotclaude")
    path = os.path.join(d, SESSION_STATE)
    # Starts that race (a tmux restore resumes every tab) take turns, so one shows a finding.
    with state_lock(path + ".lock"):
        try:
            with regular(path, os.O_RDONLY) as f:
                seen = json.load(f)
            if not isinstance(seen, dict):
                seen = {}
        except FileNotFoundError:
            seen = {}
        except (OSError, ValueError, RecursionError) as e:   # json recurses on nesting
            log(f"excluded-check state not read ({type(e).__name__}: {e})")
            seen = {}
        out = {}
        for key, lines in findings.items():
            digest = hashlib.sha256(json.dumps(sorted(lines)).encode()).hexdigest()
            if lines and seen.get(key) != digest:
                out[key] = lines
            seen.pop(key, None)
            if lines:  # none and no key read the same, and an empty key would take a slot
                seen[key] = digest  # last, so the newest keys stay
        # A closed lane's key goes with its dir and a PATH key past the newest few with its
        # tab, so the file stays small.
        paths = [k for k in seen if k.startswith(MACHINE_KEY + ":")]
        keep = set(paths[-MACHINE_KEYS:])
        seen = {k: v for k, v in seen.items()
                if k in keep or (k not in paths and os.path.isdir(k))}
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            os.makedirs(d, exist_ok=True)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, "w") as f:
                json.dump(seen, f)
            os.replace(tmp, path)
        except OSError as e:
            log(f"excluded-check state not written ({type(e).__name__}: {e})")
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return out


def regular(path, flags):
    """`path` opened never waiting (a FIFO there) and never through a link, as a regular file,
    or OSError. The state dir is any session's to write."""
    fd = os.open(path, flags | os.O_NONBLOCK | os.O_NOFOLLOW, 0o644)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise OSError(f"{path} is no regular file")
    os.set_blocking(fd, True)
    return os.fdopen(fd, "r" if flags == os.O_RDONLY else "a")


@contextlib.contextmanager
def state_lock(path, wait=2.0):
    """An flock on `path` for up to `wait` seconds; past that, or when it can't be taken at all,
    on without it (a finding then may show twice, never not at all)."""
    f = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        f = regular(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        end = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > end:
                    log("excluded-check state lock busy: going on without it")
                    break
                time.sleep(0.05)
    except OSError as e:
        log(f"excluded-check state lock not taken ({type(e).__name__}: {e})")
    try:
        yield
    finally:
        if f:
            f.close()


def session_message(shown):
    lines = [line for key in sorted(shown, key=lambda k: not k.startswith(MACHINE_KEY + ":"))
             for line in shown[key]]
    screen = ("excluded-guard: an excluded command (git push, gh, lane and the rest of "
              "sandbox.excludedCommands) from this session would be refused:\n"
              + "\n".join(f"  {line}" for line in lines)
              + "\nLook at each dir first: `python3 -I ~/.claude/hooks/excluded_guard.py --scan`"
              " (sandbox off) lists what it holds. Then add the rules to permissions.deny in "
              f"~/.claude/settings.machine.json, then {RERUN}.")
    context = ("excluded-guard will refuse excluded commands (git push, gh, lane and the rest) "
               "from this session until the user fixes: " + "; ".join(lines) + ". The fix is "
               "theirs (deny rules in their own settings): name it to them, and don't work "
               "around a refusal.")
    return {"systemMessage": screen,
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}


def run_session():
    """The SessionStart check. Fails open: any error is logged and prints nothing. Skips a
    subagent's start and an unattended one: no one would see it, and it would use up the once."""
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict) or event.get("agent_id") or \
                os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "0":
            return 0
        project = os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd")
        if not isinstance(project, str) or not os.path.isdir(project):
            return 0
        shown = unseen(session_findings(os.environ, os.path.realpath(project)))
        if shown:
            print(json.dumps(session_message(shown)))
    except Exception as e:
        log(f"excluded-check error {type(e).__name__}: {e}")
    return 0


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": "deny",
                                             "permissionDecisionReason": reason}}))


def main():
    event = json.load(sys.stdin)  # unreadable: raise, and the shim's fallback decides
    if event.get("tool_name") != "Bash":
        return
    command = (event.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        return
    env = os.environ
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else os.getcwd()
    session = str(event.get("session_id"))[:8]
    try:
        settings, errors = load_settings(env)
        heads = heads_of(matching_pieces(command, settings["excludedCommands"]))
        if errors and not heads:
            log(f"unread settings {errors}: treating as a candidate")
            heads = [first_word(normalize(command)) or "(unknown)"]
    except Exception as e:
        log(f"match error {type(e).__name__}: {e}: treating as a candidate")
        settings = {"excludedCommands": [], "denyWrite": [], "allowWrite": [], "editDeny": []}
        heads = [first_word(normalize(command)) or "(unknown)"]
    if not heads:
        return
    try:
        judge(heads, cwd, env, settings, command)
    except Refusal as r:
        log(f"deny {r.rule} {r.path} head={heads[0]} session={session}")
        deny(f"excluded-guard ({r.rule}): {r.reason}")
    except Exception as e:
        log(f"deny error {type(e).__name__}: {e} head={heads[0]} session={session}")
        deny(f"excluded-guard: could not verify `{heads[0]}` ({type(e).__name__}: {e}); refusing "
             "an excluded command it can't check.")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--scan"]:
        sys.exit(run_scan(sys.argv[2:]))
    if sys.argv[1:2] == ["--session"]:
        sys.exit(run_session())
    main()
