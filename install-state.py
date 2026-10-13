#!/usr/bin/env python3
"""install-state.py: what setup.sh's links say about lane installs, and which plugins changed.

A lane installs from its own worktree to test a change, and the next install from anywhere else
would replace those links mid-test. So the links themselves are the hold, with no state file: a
checkout holds the install while managed links point into it and it is a live lane, meaning a
linked worktree of this repo (it shares REPO_DIR's git common dir) or of another dotclaude
clone (its root holds install-state.py and setup.sh). Managed means a symlink in a dir setup.sh
links into (managed_dirs) whose path inside its checkout matches one of setup.sh's link sources
(SOURCES). setup-tmux.sh's tmux/* links, plugin-installed files and other projects' worktrees
are never touched, however their links look (another project's bin/x matches bin/*). Nor is a
worktree inside the run's own main checkout (Claude Code's agent worktrees) while it lives.

A lane's sandboxed Bash can write in its worktree, so nothing here trusts what a lane's files
say beyond the lane: a .git file naming a fake admin dir doesn't change which main releases it
(the main's own .git/worktrees/ decides), and a FIFO or a link to a device in a mod dir is
hashed by its type, never opened or read.

Usage:
  install-state.py hold REPO_DIR   exit 3, naming the holder on stderr, when a live lane other
                                   than REPO_DIR holds the install and REPO_DIR is not that
                                   lane's main checkout. A run from the main checkout relinks
                                   everything, so it proceeds and says it releases the hold.
  install-state.py prune REPO_DIR  remove the managed links into another live lane of this repo,
                                   and the dangling ones under REPO_DIR, its lanes root or an
                                   agent worktree in its main's .claude/worktrees/.
  install-state.py plugins         print one line when a mod or plugin changed since the last
                                   install: sessions started before it need /pass to load it.

`lane` imports links_into and holders from here (`lane done` refuses while links point into the
lane, `lane ls` shows the hold). Stdlib only, Python 3.8 syntax, and no tomllib or fcntl at
import: setup.sh also runs on Python 3.10 and git-bash.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shlex
import stat
import sys
from typing import NamedTuple

HELD = 3

# What setup.sh links, as paths inside its checkout (tests/setup ties these to its link lines).
SOURCES = ("CLAUDE.md", "notify-toast.ps1", "hooks/*.sh", "hooks/*.py", "skills/*",
           "skills/*/scripts/*", "agents/*.md", "templates/*.md", "bin/*", "statusline/*.py",
           "codex/AGENTS.md")
TMUX_SOURCES = ("tmux/*",)  # what setup-tmux.sh links into ~/.local/bin (and $HOME)
TMUX_START, TMUX_END = "# >>> dotclaude tmux (setup-tmux.sh) >>>", "# <<< dotclaude tmux <<<"
DOTCLAUDE = ("install-state.py", "setup.sh")  # a checkout holding both is a dotclaude checkout
AGENTS = os.path.join(".claude", "worktrees")  # Claude Code's agent worktrees, in a main checkout
MOD_SKIP = ("tests", "__pycache__")  # a mod's tests and bytecode don't change what a session loads
MOD_READ = 64 << 20  # a mod file past this counts by its size and its first MOD_READ bytes
CHUNK = 1 << 16
# Opening a mod file never follows a link or waits on a FIFO (both are checked by lstat first,
# and these close the race); O_BINARY keeps Windows from translating line ends.
OPEN = os.O_RDONLY | sum(getattr(os, f, 0) for f in ("O_NOFOLLOW", "O_NONBLOCK", "O_CLOEXEC",
                                                     "O_BINARY"))
CHANGED = "sessions started before this install need /pass to load them"


class Places(NamedTuple):
    home: str
    claude: str
    codex: str
    state: str


class Link(NamedTuple):
    path: str    # the symlink
    target: str  # where it points: parent dirs resolved, the last name not followed


class Worktree(NamedTuple):
    root: str
    main: str
    admin: str  # <common>/worktrees/<x>


class Run(NamedTuple):
    """Where a setup.sh run stands."""
    me: str              # its checkout, resolved
    common: str | None   # that checkout's git common dir
    main: str            # its main checkout: the common dir's parent (me, outside git)
    lanes: str | None    # its repo's lanes root, from the lanes config


def places(env=None) -> Places:
    """Where setup.sh installs, from the variables it reads."""
    env = os.environ if env is None else env
    home = env.get("HOME") or os.path.expanduser("~")
    state = env.get("XDG_STATE_HOME") or os.path.join(home, ".local", "state")
    return Places(home, env.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude"),
                  env.get("CODEX_HOME") or os.path.join(home, ".codex"),
                  os.path.join(state, "dotclaude"))


def managed_dirs(p: Places) -> list[str]:
    """The dirs setup.sh links into, each read one level deep."""
    dirs = [p.claude] + [os.path.join(p.claude, d) for d in ("hooks", "skills", "agents", "templates")]
    dirs += [os.path.join(p.home, ".local", "bin"), p.codex, os.path.join(p.codex, "skills"),
             os.path.join(p.home, ".config", "ccstatusline")]
    return list(dict.fromkeys(dirs))


def pointed(path: str) -> str:
    """path with its parent dirs resolved but not its last name: where a link points, not where
    that leads (a repo file that is itself a link stays in its checkout)."""
    parent, name = os.path.split(path.rstrip(os.sep) or os.sep)
    if name in ("", ".", ".."):
        return os.path.realpath(path)
    return os.path.join(os.path.realpath(parent), name)


def inside(path: str, root: str) -> bool:
    """path is root or below it (both already resolved)."""
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def links(p: Places) -> list[Link]:
    """Every symlink in the managed dirs."""
    out = []
    for d in managed_dirs(p):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            path = os.path.join(d, name)
            try:
                raw = os.readlink(path)
            except OSError:  # not a link
                continue
            out.append(Link(path, pointed(os.path.join(d, raw))))
    return out


def managed(rel: str, globs: tuple[str, ...] = SOURCES) -> bool:
    """rel, a path inside a checkout, is one setup.sh links: it matches a SOURCES glob (or one of
    globs) segment by segment, so a * never spans a /."""
    parts = rel.replace(os.sep, "/").split("/")
    for glob in globs:
        pats = glob.split("/")
        if len(pats) == len(parts) and all(map(fnmatch.fnmatchcase, parts, pats)):
            return True
    return False


def installer(rel: str) -> str:
    """What relinks a link to rel, a path inside its checkout."""
    if managed(rel):
        return "setup.sh"
    return "setup-tmux.sh" if managed(rel, TMUX_SOURCES) else "by hand"


def below(path: str, root: str) -> str | None:
    """path's part under <root>/<one dir>/ (a lane's id, an agent worktree's name, stripped);
    None when path isn't that deep under root."""
    if not inside(path, root):
        return None
    parts = os.path.relpath(path, root).split(os.sep, 1)
    return parts[1] if len(parts) == 2 else None


def show(link: Link, p: Places) -> str:
    home = p.home.rstrip(os.sep)
    path = "~" + link.path[len(home):] if inside(link.path, home) else link.path
    return f"{path} -> {link.target}"


def checkout_of(path: str) -> str | None:
    """The nearest dir above path holding a .git, as git finds a checkout; None if none does."""
    d = os.path.dirname(path)
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def gitdir_file(root: str) -> str | None:
    """The dir root/.git names when it is a file (a linked worktree's, a submodule's), resolved."""
    dotgit = os.path.join(root, ".git")
    try:
        if not stat.S_ISREG(os.lstat(dotgit).st_mode):
            return None
        with open(dotgit, encoding="utf-8") as f:
            line = f.read().strip()
    except (OSError, ValueError):  # ValueError: not UTF-8
        return None
    if not line.startswith("gitdir:"):
        return None
    return os.path.realpath(os.path.join(root, line[len("gitdir:"):].strip()))


def linked_worktree(root: str) -> Worktree | None:
    """root as a live linked worktree, else None: its .git file names <common>/worktrees/<x>,
    whose gitdir file names that .git back, and root sits outside the main checkout and the
    common dir (lanelib.worktree_problem's check). So a planted worktrees/ entry can't make the
    main checkout, or a plain dir, a holder."""
    root = os.path.realpath(root)
    admin = gitdir_file(root)
    if admin is None or os.path.basename(os.path.dirname(admin)) != "worktrees":
        return None
    try:
        with open(os.path.join(admin, "gitdir"), encoding="utf-8") as f:
            back = os.path.realpath(os.path.join(admin, f.read().strip()))
    except (OSError, ValueError):
        return None
    common = os.path.dirname(os.path.dirname(admin))
    main = os.path.dirname(common)
    if back != os.path.join(root, ".git") or inside(root, main) or inside(root, common):
        return None
    return Worktree(root, main, admin)


def worktree_at(target: str) -> Worktree | None:
    """The live linked worktree a link target sits in, or None."""
    root = checkout_of(target)
    return linked_worktree(root) if root else None


def registered(common: str | None) -> dict[str, str]:
    """root -> admin dir for each worktree that common's own worktrees/<x>/gitdir names back
    (<root>/.git): the linked worktrees git lists for that repo, whatever each root's .git file
    says. A lane's sandboxed Bash can rewrite its .git file to name a fake admin elsewhere."""
    out: dict[str, str] = {}
    top = os.path.join(common, "worktrees") if common else None
    try:
        names = sorted(os.listdir(top)) if top else []
    except OSError:
        names = []
    for name in names:
        admin = os.path.join(top, name)
        try:
            with open(os.path.join(admin, "gitdir"), encoding="utf-8") as f:
                back = os.path.realpath(os.path.join(admin, f.read().strip()))
        except (OSError, ValueError):
            continue
        if os.path.basename(back) == ".git":
            out.setdefault(os.path.dirname(back), admin)
    return out


def run_at(repo_dir: str, p: Places) -> Run:
    me = os.path.realpath(repo_dir)
    common = common_dir(me)
    return Run(me, common, os.path.dirname(common) if common else me, lanes_root(common, p))


def branch(wt: Worktree) -> str:
    try:
        with open(os.path.join(wt.admin, "HEAD"), encoding="utf-8") as f:
            head = f.read().strip()
    except (OSError, ValueError):
        return "?"
    ref = "ref: refs/heads/"
    return head[len(ref):] if head.startswith(ref) else f"detached at {head[:12]}"


def lane_of(wt: Worktree, common: str | None) -> bool:
    """wt is a lane of the repo whose git common dir is common."""
    return common is not None and common_dir(wt.root) == common


def holders(repo_dir: str, env=None) -> list[dict]:
    """Each live lane other than repo_dir that managed links point into, by root: {"root",
    "main", "branch", "links"}, links as `~/.claude/hooks/x.sh -> <target>`. A lane is a linked
    worktree of this repo, or a dotclaude checkout's (both DOTCLAUDE files at its root), so a
    plain clone elsewhere is still refused while the real repo's lane holds. Another project's
    worktree never holds, nor does one inside repo_dir's main checkout. A holder this repo's own
    .git/worktrees/ registers gets this repo's main and its admin dir there, whatever its .git
    file names."""
    p = places(env)
    run = run_at(repo_dir, p)
    ours = registered(run.common)
    found = {}
    for link in links(p):
        wt = worktree_at(link.target)
        if (wt is None or wt.root == run.me or inside(wt.root, run.main)
                or not managed(os.path.relpath(link.target, wt.root))
                or not (lane_of(wt, run.common)
                        or all(os.path.isfile(os.path.join(wt.root, f)) for f in DOTCLAUDE))):
            continue
        if wt.root in ours:
            wt = Worktree(wt.root, run.main, ours[wt.root])
        found.setdefault(wt, []).append(show(link, p))
    return [{"root": wt.root, "main": wt.main, "branch": branch(wt), "links": shown}
            for wt, shown in sorted(found.items())]


def hold(repo_dir: str, env=None) -> tuple[list[dict], list[dict]]:
    """(the holders a run from repo_dir must not replace, the ones it releases). A run from a
    holder's main checkout relinks everything, so it releases that holder: one whose .git file
    names it, or any its own .git/worktrees/ registers. Only a main checkout (a real .git dir)
    releases: a lane whose own .git file names a common dir it planted would otherwise read its
    run as main and release a sibling."""
    me = os.path.realpath(repo_dir)
    dotgit = os.path.join(me, ".git")
    main = os.path.isdir(dotgit) and not os.path.islink(dotgit)
    held, released = [], []
    for h in holders(repo_dir, env):
        (released if main and h["main"] == me else held).append(h)
    return held, released


def tmux_block(path: str) -> list[str]:
    """The lines inside ~/.tmux.conf's setup-tmux.sh block (to its end marker, or the file's)."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except (OSError, ValueError):
        return []
    if TMUX_START not in lines:
        return []
    block = lines[lines.index(TMUX_START) + 1:]
    return block[:block.index(TMUX_END)] if TMUX_END in block else block


def links_into(path: str, env=None) -> list[str]:
    """Every link in the managed dirs pointing into path, a checkout's root (a lane's), glob or
    not (setup-tmux.sh's ~/.local/bin links count), plus each line of the ~/.tmux.conf block
    naming a path inside it. Each line ends with what relinks it: " (setup.sh)" for a managed
    link, " (setup-tmux.sh)" for a tmux/* link and each block line, " (by hand)" for any other.
    `lane done` refuses while this is non-empty: removing the worktree would break them."""
    p = places(env)
    root = os.path.realpath(path)
    out = [f"{show(link, p)} ({installer(os.path.relpath(link.target, root))})"
           for link in links(p) if inside(link.target, root)]
    conf = os.path.join(p.home, ".tmux.conf")
    for line in tmux_block(conf):
        try:
            words = shlex.split(line, comments=True)
        except ValueError:  # unbalanced quotes
            words = line.split()
        if any(os.path.isabs(w) and inside(pointed(w), root) for w in words):
            out.append(f"~/.tmux.conf: {line.strip()} (setup-tmux.sh)")
    return out


def common_dir(checkout: str) -> str | None:
    """checkout's git common dir, as `git rev-parse --git-common-dir` finds it: its .git dir, or
    the dir a .git file names, through that dir's commondir file when it has one."""
    checkout = os.path.realpath(checkout)
    dotgit = os.path.join(checkout, ".git")
    if os.path.isdir(dotgit) and not os.path.islink(dotgit):
        return dotgit
    gitdir = gitdir_file(checkout)
    if gitdir is None:
        return None
    try:
        with open(os.path.join(gitdir, "commondir"), encoding="utf-8") as f:
            return os.path.realpath(os.path.join(gitdir, f.read().strip()))
    except FileNotFoundError:
        return gitdir
    except (OSError, ValueError):
        return None


def config_root(text: str) -> str | None:
    """The `root` key of a lanes config. `lane init` writes flat `key = "value"` lines, so where
    tomllib is missing (before 3.11) a regex reads the same value."""
    try:
        import tomllib  # here, not at the top: this module must import on Python 3.10
    except ImportError:
        m = re.search(r'^root\s*=\s*"((?:[^"\\]|\\.)*)"\s*(?:#.*)?$', text, re.M)
        if not m:
            return None
        return re.sub(r"\\(.)", lambda e: {"n": "\n", "t": "\t"}.get(e.group(1), e.group(1)),
                      m.group(1))
    try:
        root = tomllib.loads(text).get("root")
    except tomllib.TOMLDecodeError:
        return None
    return root if isinstance(root, str) else None


def lanes_root(common: str | None, p: Places) -> str | None:
    """The lanes root of the repo whose git common dir is common, from the config `lane init`
    wrote (lanelib.Repo.config_path); None without one."""
    if common is None:
        return None
    key = hashlib.sha256(common.encode()).hexdigest()[:12]
    name = f"{os.path.basename(os.path.dirname(common))}-{key}.toml"
    try:
        with open(os.path.join(p.state, "lanes", name), encoding="utf-8") as f:
            root = config_root(f.read())
    except (OSError, ValueError):
        return None
    return os.path.realpath(root) if root and os.path.isabs(root) else None


def stale(link: Link, run: Run) -> bool:
    """A managed link this run should remove: into a live lane of this repo (a linked worktree
    sharing run.common) other than run.me and outside run.main, or dangling under an agent
    worktree in run.main, under run.me or under a lane in the lanes root. A link into another
    repo's worktree is never stale here, dotclaude-shaped or not."""
    wt = worktree_at(link.target)
    if wt and wt.root != run.me and not inside(wt.root, run.main) and lane_of(wt, run.common):
        rel = os.path.relpath(link.target, wt.root)
    elif os.path.exists(link.path):
        return False
    elif inside(link.target, os.path.join(run.main, AGENTS)):  # before me, which may hold it
        rel = below(link.target, os.path.join(run.main, AGENTS))
    elif inside(link.target, run.me):
        rel = os.path.relpath(link.target, run.me)
    else:
        rel = below(link.target, run.lanes) if run.lanes else None
    return rel is not None and managed(rel)


def prune(repo_dir: str, env=None, say=None) -> list[str]:
    """Remove the stale managed links (see stale); one line per removal, returned and passed to
    say as each happens. A link that can't be checked or removed is named on stderr and left.
    Regular files, links outside the managed dirs, links matching no source and links into other
    repos are never touched."""
    p = places(env)
    run = run_at(repo_dir, p)
    out = []
    for link in links(p):
        try:
            if not stale(link, run) or not os.path.islink(link.path):
                continue
            os.unlink(link.path)
        except FileNotFoundError:  # gone meanwhile
            continue
        except OSError as e:
            sys.stderr.write(f"!!  couldn't prune the link {show(link, p)} "
                             f"({e.strerror or e}); left in place\n")
            continue
        out.append(f"removed link {show(link, p)}")
        if say:
            say(out[-1])
    return out


def entry_digest(path: str) -> bytes:
    """What one entry of a mod adds to its hash, never blocking on it or reading without end: a
    regular file's size and content digest (to MOD_READ), a link's own target text (never
    followed), and for anything else (a FIFO, a socket, a device) only its type."""
    try:
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode):
            return b"link\0" + os.fsencode(os.readlink(path))
        if not stat.S_ISREG(st.st_mode):
            return b"type\0%o" % stat.S_IFMT(st.st_mode)
        fd = os.open(path, OPEN)
    except OSError:
        return b"unreadable"
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):  # swapped in since the lstat
            return b"type\0%o" % stat.S_IFMT(st.st_mode)
        h, left = hashlib.sha256(), min(st.st_size, MOD_READ)
        while left > 0:
            chunk = os.read(fd, min(CHUNK, left))
            if not chunk:
                break
            h.update(chunk)
            left -= len(chunk)
    except OSError:
        return b"unreadable"
    finally:
        os.close(fd)
    return b"file\0%d\0%s" % (st.st_size, h.digest())


def tree_hash(d: str) -> str:
    """sha256 over a mod's entries (relative paths and entry_digest), minus MOD_SKIP dirs. A
    linked subdir counts as a link: os.walk lists it but doesn't follow it."""
    paths = []
    for top, dirs, names in os.walk(d):
        dirs[:] = [x for x in dirs if x not in MOD_SKIP]
        paths += [os.path.join(top, n) for n in names]
        paths += [os.path.join(top, x) for x in dirs if os.path.islink(os.path.join(top, x))]
    h = hashlib.sha256()
    for path in sorted(paths):
        rel = os.path.relpath(path, d).replace(os.sep, "/").encode("utf-8", "surrogateescape")
        entry = entry_digest(path)
        h.update(b"%d\0%s%d\0%s" % (len(rel), rel, len(entry), entry))
    return h.hexdigest()


def mod_name(d: str, manifest: str) -> str:
    """The manifest's name plus @skills-dir, as Claude Code names a skills-dir mod; else the dir's."""
    try:
        with open(manifest, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    name = data.get("name") if isinstance(data, dict) else None
    return f"{name}@skills-dir" if isinstance(name, str) and name else os.path.basename(d)


def fingerprint(p: Places) -> dict:
    """name -> what a session loads at start: each mod's tree_hash, and each installed plugin's
    [version, gitCommitSha] per install entry. A plain skill (no .claude-plugin/) is left out:
    running sessions pick up SKILL.md text live."""
    out = {}
    skills = os.path.join(p.claude, "skills")
    try:
        names = sorted(os.listdir(skills))
    except OSError:
        names = []
    for name in names:
        d = os.path.join(skills, name)
        manifest = os.path.join(d, ".claude-plugin", "plugin.json")
        if os.path.isfile(manifest):
            out[mod_name(d, manifest)] = tree_hash(d)
    try:
        with open(os.path.join(p.claude, "plugins", "installed_plugins.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = None
    plugins = data.get("plugins") if isinstance(data, dict) else None
    for name, entries in (plugins.items() if isinstance(plugins, dict) else ()):
        entries = entries if isinstance(entries, list) else [entries]
        out[name] = sorted([str(e.get("version") or ""), str(e.get("gitCommitSha") or "")]
                           for e in entries if isinstance(e, dict))
    return out


def plugin_change(env=None) -> str | None:
    """Compare the fingerprint with the last install's and save the new one; the line to print
    when they differ, None when they match or there was no baseline. A whole-dir skill link makes
    edits live on disk, so only a saved baseline can see them."""
    p = places(env)
    path = os.path.join(p.state, "install-plugins.json")
    new = fingerprint(p)
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = None
    os.makedirs(p.state, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(new, f, indent=1, sort_keys=True)
    os.replace(tmp, path)
    if not isinstance(old, dict) or old == new:
        return None
    parts = ([f"{n} added" for n in sorted(new.keys() - old.keys())]
             + [f"{n} removed" for n in sorted(old.keys() - new.keys())]
             + [f"{n} changed" for n in sorted(new.keys() & old.keys()) if new[n] != old[n]])
    return f"plugins changed ({', '.join(parts)}): {CHANGED}"


def link_count(h: dict) -> str:
    n = len(h["links"])
    return f"{n} link{'' if n == 1 else 's'}"


def main(argv: list[str]) -> int:
    cmd, args = (argv[1], argv[2:]) if len(argv) > 1 else ("", [])
    if cmd == "hold" and len(args) == 1:
        held, released = hold(args[0])
        for h in held:
            sys.stderr.write(
                f"!!  install held by the lane worktree {h['root']} (branch {h['branch']}, "
                f"{link_count(h)} into it): its install is under test. The lead's ./setup.sh in "
                f"{h['main']} releases it (it relinks everything).\n")
        if held:
            return HELD
        for h in released:
            print(f"==> this run releases the install held by {h['root']} "
                  f"(branch {h['branch']}, {link_count(h)}): it relinks everything")
        return 0
    if cmd == "prune" and len(args) == 1:
        prune(args[0], say=lambda line: print(f"==> {line}", flush=True))
        return 0
    if cmd == "plugins" and not args:
        line = plugin_change()
        if line:
            print(f"!!  {line}")
        return 0
    sys.stderr.write(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
