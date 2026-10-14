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
     the cwd's repo or the project's, is refused.
  2. The PATH the head resolves through. Every PATH entry must be protected, not only those
     before the head: its children (git, gh, tmux, the tools claude spawns) search PATH too. An
     empty or relative entry is the cwd: refused. Then the resolved file's symlink chain (each
     hop and the dir of each) and a shebang interpreter (`#!/usr/bin/env X` resolves X through
     PATH), depth capped at 3.
  3. `claude` and `codex` run only from the project root.

Protected means not writable in the machine view. A path (or, if missing, its nearest existing
ancestor, at its target when that ancestor is a symlink) is writable when it sits under a root ($HOME, /tmp, $TMPDIR or an allowWrite entry;
realpaths compared), no denyWrite entry, ~/.claude or ~/.gitconfig covers it, and some component
from it up to its root is owned by the user or writable by the user. Permission bits are not
protection: an owner can chmod a dir back, and a writable parent can rename it. Outside every
root is protected (/usr/bin, /etc). ~/.gitconfig counts only as a regular file at that exact
path; a symlink there is judged by its hops and target. PATH dirs are shared by every session,
so "this session can't write it" is not enough.

Which calls are candidates: a pattern's `*` matches any characters, spaces included; the rest is
literal. A call is a candidate when the whole command matches, or any piece does after splitting
on newlines, `;`, `&&`, `||`, `|` and `&` (not quote-aware, so it over-matches: an over-match only
adds checks to a sandboxed call). excludedCommands and allowWrite are the union of user, managed,
project and project-local files (more candidates, more writable: both safe). denyWrite counts
only from user and managed files: the machine view stands for every session, and other sessions
don't load this project's settings.

Fails closed for candidates: any error while matching makes the call a candidate, and any error
while checking one refuses it. A non-candidate exits silently. An unreadable payload raises, so
the shim's head-word fallback decides. Denies go to $XDG_STATE_HOME/dotclaude/excluded-guard.log.
"""
import glob
import json
import os
import re
import shlex
import sys
import time

MANAGED_DIR = "/etc/claude-code"
MANAGED_ENV = "EXCLUDED_GUARD_MANAGED_DIR"  # tests point this at a temp dir
SPLIT = re.compile(r"\n|&&|\|\||;|\||&")
ASSIGN = re.compile(r"""[A-Za-z_][A-Za-z0-9_]*=("[^"]*"|'[^']*'|\S*)\s*""")
PROJECT_HEADS = {"claude", "codex"}
SHEBANG_DEPTH = 3
INCLUDE_DEPTH = 10
# Only user and managed denyWrite count (load_settings), so the hint names where an entry lands.
DENY_HINT = ("Add it to sandbox.filesystem.denyWrite in user or managed settings, since a "
             "project's own don't count (dotclaude: ~/.claude/settings.machine.json, then "
             "./setup.sh)")


def log(line):
    try:
        d = os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                         "dotclaude")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "excluded-guard.log"), "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + line + "\n")
    except OSError:
        pass


class Refusal(Exception):
    def __init__(self, rule, path, reason):
        super().__init__(reason)
        self.rule, self.path, self.reason = rule, path, reason


# --- Settings ----------------------------------------------------------------------------------

def expand(path, home):
    if path == "~" or path.startswith("~/"):
        return home + path[1:]
    return path


def load_settings(env):
    """Union of excludedCommands and allowWrite from user, managed, project and project-local
    settings; denyWrite from user and managed only. Returns (settings, errors): a file that
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
    out = {"excludedCommands": [], "denyWrite": [], "allowWrite": []}
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
        except (OSError, ValueError) as e:
            errors.append(f"{path}: {type(e).__name__}")
            continue
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


def candidates(command, patterns):
    """The heads of every matching piece (whole command first). Empty: not a candidate."""
    regexes = [pattern_re(p) for p in patterns]
    heads = []
    pieces = [command.strip(), normalize(command)] + [normalize(p) for p in SPLIT.split(command)]
    for piece in pieces:
        if piece and any(r.fullmatch(piece) for r in regexes):
            head = first_word(normalize(piece))
            if head and head not in heads:
                heads.append(head)
    return heads


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
        deny = settings["denyWrite"]
        self.deny = ([os.path.abspath(d) for d in deny] + [os.path.realpath(d) for d in deny]
                     + [self.resolved(os.path.abspath(d)) for d in deny]
                     + [os.path.join(self.home, ".claude")])
        self.gitconfig = os.path.join(self.home, ".gitconfig")

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
        for _ in range(40):
            if self.always_protected(p):
                return p
            # A file or symlink is replaced by whoever writes its dir; a real dir stands on its
            # own, as a PATH entry does.
            real_dir = os.path.isdir(p) and not os.path.islink(p)
            for x in (p,) if real_dir else (p, os.path.dirname(p)):
                bad = self.exposed(x)
                if bad:
                    raise refuse(bad)
            if not os.path.islink(p):
                return p
            p = os.path.normpath(os.path.join(os.path.dirname(p), os.readlink(p)))
        raise Refusal(rule, p, f"{path} has a symlink loop at {p}; could not verify it.")


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


def check_rule1(m, env, cwd, project):
    repo = discover(cwd, env)
    proj = discover(project, {k: env[k] for k in ("GIT_CEILING_DIRECTORIES",) if k in env})
    if repo and (proj is None or repo[1] != proj[1]):
        raise Refusal("rule1", repo[0],
                      f"the working directory resolves to the git dir {repo[0]}, not the project's "
                      "repository. Run it from the project's repository.")
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
                f"write ({bad}). {DENY_HINT}."))
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
                       f"often sets it. {DENY_HINT}.")
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

def path_refusal(head, path):
    return Refusal("rule2", path, f"`{head}` resolves through {path}, which a sandboxed session "
                   f"can write. {DENY_HINT}, or drop it from PATH.")


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
            m.chain(entry, "rule2", lambda bad: path_refusal(label, bad))
        else:
            bad = m.exposed(entry)
            if bad:
                raise path_refusal(label, bad)
        cand = os.path.join(entry, head)
        if found is None and os.path.isfile(cand) and os.access(cand, os.X_OK):
            found = cand
    if found:
        check_file(m, found, path_var, label, depth)


def check_file(m, path, path_var, label, depth):
    if depth > SHEBANG_DEPTH:
        raise Refusal("rule2", path, f"`{label}` runs through more than {SHEBANG_DEPTH} "
                      "interpreters; could not verify it.")
    p = m.chain(path, "rule2", lambda bad: path_refusal(label, bad))
    try:
        with open(p, "rb") as f:
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
                raise path_refusal(head, bad)
    else:
        which(m, head, path_var, head, 0)


# --- Rule 3 and the verdict --------------------------------------------------------------------

def check_rule3(head, cwd, project):
    if os.path.basename(head) in PROJECT_HEADS and \
            os.path.realpath(cwd) != os.path.realpath(project):
        raise Refusal("rule3", cwd, f"`{os.path.basename(head)}` reads the working directory's "
                      f"project config, and {cwd} is not the project root. Run claude/codex from "
                      "the project root.")


def judge(heads, cwd, env, settings):
    project = env.get("CLAUDE_PROJECT_DIR")
    if not project:
        raise Refusal("project", "(unset)", "CLAUDE_PROJECT_DIR is unset, so the guard can't tell "
                      "the project's repository; refusing an excluded command.")
    m = Machine(env, settings, cwd)
    check_rule1(m, env, cwd, project)
    for head in heads:
        check_rule2(m, head, env.get("PATH", ""))
        check_rule3(head, cwd, project)


# --- Scan ----------------------------------------------------------------------------------------

SCAN_DEPTH = 4


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
    Returns [(where, Refusal)] and the settings read errors."""
    env = {k: v for k, v in env.items() if k != "CLAUDE_PROJECT_DIR"}
    settings, errors = load_settings(env)
    heads = sorted({first_word(normalize(p)) for p in settings["excludedCommands"]} - {""})
    found = []
    m = Machine(env, settings, env.get("HOME") or os.getcwd())
    for head in heads:
        try:
            check_rule2(m, head, env.get("PATH", ""))
        except Refusal as r:
            found.append(("PATH", r))
    for root in roots:
        for repo in repos_under(root):
            try:
                check_rule1(Machine(env, settings, repo), env, repo, repo)
            except Refusal as r:
                found.append((repo, r))
    return found, errors


def run_scan(roots):
    """Print each refusal once per path, then the denyWrite lines that would clear them.
    Exits 1 when anything would be refused."""
    found, errors = scan(roots or [os.path.expanduser("~")], os.environ)
    for e in errors:
        print(f"settings not read: {e}")
    first = {}
    for where, r in found:
        first.setdefault(r.path, (where, r))
    for where, r in first.values():
        print(f"{where}: excluded-guard ({r.rule}): {r.reason}")
    fix = [p for p, (_, r) in first.items() if DENY_HINT in r.reason and os.path.isabs(p)]
    if fix:
        print("denyWrite lines for ~/.claude/settings.machine.json, then ./setup.sh:")
        for p in fix:
            print(f"  {json.dumps(p)},")
    return 1 if first or errors else 0


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
        heads = candidates(command, settings["excludedCommands"])
        if errors and not heads:
            log(f"unread settings {errors}: treating as a candidate")
            heads = [first_word(normalize(command)) or "(unknown)"]
    except Exception as e:
        log(f"match error {type(e).__name__}: {e}: treating as a candidate")
        settings = {"excludedCommands": [], "denyWrite": [], "allowWrite": []}
        heads = [first_word(normalize(command)) or "(unknown)"]
    if not heads:
        return
    try:
        judge(heads, cwd, env, settings)
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
    main()
