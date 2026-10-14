"""PreToolUse(Bash) guard for excluded commands; hooks/excluded-guard.sh runs it.

Rule: a command that runs outside the sandbox (one matching `sandbox.excludedCommands`) must not
act on anything a sandboxed session can write. For a call that matches, three checks:

  1. The git config the cwd resolves to. A repo at the cwd must be the project's own repository
     (same common git dir as CLAUDE_PROJECT_DIR); a nested repo, a planted gitfile or a repo in a
     temp dir is refused. Every other config file git reads (global, XDG, system, each
     include.path / includeIf.*.path target, recursively, and a core.hooksPath target) must be
     protected. The project repo's own config, hooks/ and config.worktree are trusted: Claude
     Code protects them for the session.
  2. The PATH the head resolves through. Every PATH entry searched up to and including the one
     holding the head must be protected (an empty or relative entry is the cwd: refused), then
     the resolved file, each symlink hop and each one's dir, and a shebang interpreter
     (`#!/usr/bin/env X` resolves X through PATH), depth capped at 3.
  3. `claude` and `codex` run only from the project root.

Protected means not writable in the machine view: a path (or its nearest existing ancestor) is
writable when the user can write it on disk, it sits under $HOME, /tmp, $TMPDIR or an allowWrite
entry, and no denyWrite entry, ~/.claude or ~/.gitconfig covers it. PATH dirs are shared by every
session, so "this session can't write it" is not enough.

Which calls are candidates: a pattern's `*` matches any characters, spaces included; the rest is
literal. A call is a candidate when the whole command matches, or any piece does after splitting
on newlines, `;`, `&&`, `||`, `|` and `&` (not quote-aware, so it over-matches: an over-match only
adds checks to a sandboxed call). Settings are the union of user, managed, project and
project-local files.

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
    """Union of excludedCommands, denyWrite and allowWrite. Returns (settings, errors): a file
    that exists but can't be read makes the call a candidate (we may have missed a pattern)."""
    home = env.get("HOME") or os.path.expanduser("~")
    managed = env.get(MANAGED_ENV) or MANAGED_DIR
    files = [os.path.join(home, ".claude", "settings.json"),
             os.path.join(managed, "managed-settings.json")]
    files += sorted(glob.glob(os.path.join(managed, "managed-settings.d", "*.json")))
    project = env.get("CLAUDE_PROJECT_DIR")
    if project:
        files += [os.path.join(project, ".claude", "settings.json"),
                  os.path.join(project, ".claude", "settings.local.json")]
    out = {"excludedCommands": [], "denyWrite": [], "allowWrite": []}
    errors = []
    for path in files:
        try:
            with open(path) as f:
                data = json.load(f)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as e:
            errors.append(f"{path}: {type(e).__name__}")
            continue
        sandbox = data.get("sandbox") if isinstance(data, dict) else None
        if not isinstance(sandbox, dict):
            continue
        fs = sandbox.get("filesystem") if isinstance(sandbox.get("filesystem"), dict) else {}
        for key, src in (("excludedCommands", sandbox), ("denyWrite", fs), ("allowWrite", fs)):
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
                     + [os.path.join(self.home, ".claude")])
        self.gitconfig = os.path.join(self.home, ".gitconfig")

    def resolved(self, p):
        """Realpath, but a symlink itself stays itself (it can be replaced by its dir's owner)."""
        if os.path.islink(p):
            return os.path.join(os.path.realpath(os.path.dirname(p)), os.path.basename(p))
        return os.path.realpath(p)

    def writable(self, path):
        p = os.path.abspath(os.path.join(self.cwd, path))
        q = p
        while not os.path.lexists(q):
            q = os.path.dirname(q)
        if os.path.islink(q):
            ok = os.access(os.path.dirname(q), os.W_OK)
        elif os.path.isdir(q):
            ok = os.access(q, os.W_OK)
        else:
            ok = os.access(q, os.W_OK) or os.access(os.path.dirname(q), os.W_OK)
        if not ok:
            return False
        real = self.resolved(q)
        if not any(under(real, r) for r in self.roots):
            return False
        if real == self.gitconfig or os.path.realpath(p) == self.gitconfig:
            return False
        for d in self.deny:
            if under(real, d) or under(p, d) or under(q, d):
                return False
        return True

    def exposed(self, path):
        """The first writable thing along `path` (a symlinked ancestor, then the path), or None."""
        p = os.path.abspath(os.path.join(self.cwd, path))
        parts = p.strip("/").split("/")
        for i in range(1, len(parts)):
            a = "/" + "/".join(parts[:i])
            if os.path.islink(a) and self.writable(a):
                return a
        return p if self.writable(p) else None


# --- Rule 1: git config ------------------------------------------------------------------------

def gitdir_info(gitdir):
    gitdir = os.path.realpath(gitdir)
    common = gitdir
    try:
        with open(os.path.join(gitdir, "commondir")) as f:
            common = os.path.realpath(os.path.join(gitdir, f.read().strip()))
    except FileNotFoundError:
        pass
    return gitdir, common


def read_gitfile(path):
    with open(path) as f:
        line = f.readline().strip()
    if not line.startswith("gitdir:"):
        raise ValueError(f"invalid gitfile {path}")
    target = line[len("gitdir:"):].strip()
    return os.path.join(os.path.dirname(path), target)


def looks_like_gitdir(d):
    return (os.path.isfile(os.path.join(d, "HEAD"))
            and os.path.isdir(os.path.join(d, "objects")) and os.path.isdir(os.path.join(d, "refs")))


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
            return gitdir_info(dotgit) + (d,)
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
        trusted = [os.path.join(common, "config"), os.path.join(gitdir, "config.worktree")]
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
        if path in seen or not os.path.isfile(path):
            continue
        seen.add(path)
        if not is_trusted:
            bad = m.exposed(path)
            if bad:
                raise Refusal("rule1", bad, f"git reads the config file {path}, which a sandboxed "
                              f"session can write ({bad}). Add it to sandbox.filesystem.denyWrite.")
        includes, hooks = config_refs(path, home)
        if depth < INCLUDE_DEPTH:
            queue += [(i, False, depth + 1) for i in includes]
        for h in hooks:
            hdir = os.path.join(hooks_base, h)
            bad = m.exposed(hdir)
            if not bad and os.path.isdir(hdir):
                bad = next((x for x in (m.exposed(os.path.join(hdir, n))
                                        for n in sorted(os.listdir(hdir))) if x), None)
            if bad:
                raise Refusal("rule1", bad, f"core.hooksPath points at {hdir}, which a sandboxed "
                              f"session can write ({bad}). Add it to sandbox.filesystem.denyWrite.")


# --- Rule 2: PATH ------------------------------------------------------------------------------

def path_refusal(head, path):
    return Refusal("rule2", path, f"`{head}` resolves through {path}, which a sandboxed session "
                   "can write. Add it to sandbox.filesystem.denyWrite or drop it from PATH.")


def which(m, head, path_var, label, depth):
    """Walk PATH for `head`, refusing an unprotected entry searched before it is found."""
    for entry in path_var.split(":"):
        if not entry or not os.path.isabs(entry):
            raise Refusal("rule2", entry or "(empty)",
                          f"PATH holds {entry or 'an empty entry'!r}, which searches the working "
                          f"directory for `{label}`. Drop it from PATH.")
        bad = m.exposed(entry)
        if bad:
            raise path_refusal(label, bad)
        cand = os.path.join(entry, head)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            check_file(m, cand, path_var, label, depth)
            return


def check_file(m, path, path_var, label, depth):
    if depth > SHEBANG_DEPTH:
        raise Refusal("rule2", path, f"`{label}` runs through more than {SHEBANG_DEPTH} "
                      "interpreters; could not verify it.")
    p = os.path.abspath(os.path.join(m.cwd, path))
    for _ in range(40):
        for x in (p, os.path.dirname(p)):
            bad = m.exposed(x)
            if bad:
                raise path_refusal(label, bad)
        if not os.path.islink(p):
            break
        p = os.path.normpath(os.path.join(os.path.dirname(p), os.readlink(p)))
    else:
        raise Refusal("rule2", p, f"`{label}` has a symlink loop at {p}; could not verify it.")
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
    main()
