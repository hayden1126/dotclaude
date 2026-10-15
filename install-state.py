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

A lane's sandboxed Bash can write in its worktree (its .git file too) and in its repo's
.git/worktrees/, so nothing here trusts what a lane's files say beyond the lane: a .git file
naming a fake admin dir doesn't change which main releases it (the main's own .git/worktrees/
decides), and a FIFO or a link to a device in a mod dir is hashed by its type, never opened or
read.

The invariant: no file read here can block or read without bound. Every file this module reads
goes through read_bounded (git's metadata: a .git file, an admin dir's gitdir, HEAD and
commondir; a mod's plugin.json, installed_plugins.json, the saved fingerprint, the lanes config
and ~/.tmux.conf), except a mod's entries, which entry_digest reads in chunks for tree_hash.
read_bounded opens without following a link (~/.tmux.conf alone follows one) and without waiting
on a FIFO, reads only a regular file, and stops at a per-file limit (GIT_READ, TEXT_READ,
JSON_READ): a FIFO, a device, a link, a dir, a file past its limit or one it can't read all read
as absent. tests/setup sweeps each of those files with a FIFO, a link to /dev/zero and a 2 GiB
file, and fails on any other open() of a file to read. The one git call (commits_past, from
merged_refusal) runs only in a lane's own run, once those reads have validated the worktree and
read its HEAD and commondir, and stops after GIT_WAIT.

Usage:
  install-state.py hold REPO_DIR   exit 3, naming the holder on stderr, when a live lane other
                                   than REPO_DIR holds the install and REPO_DIR is not that
                                   lane's main checkout. A run from the main checkout relinks
                                   everything, so it proceeds and says it releases the hold.
                                   Exit 3 too when REPO_DIR is a lane with no commit past the
                                   lanes config's base (merged, or nothing committed yet), or
                                   when git can't tell: its install would take the live install
                                   back from main.
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
GIT_WAIT = 5  # seconds for merged_refusal's git: hold must finish inside tests/setup's 10 s sweep

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
# read_bounded's limits, past which a file reads as absent. GIT_READ: one path or ref (PATH_MAX
# plus "gitdir: " fits). TEXT_READ: a manifest, the lanes config, ~/.tmux.conf. JSON_READ:
# installed_plugins.json and the saved fingerprint, which grow with each plugin.
GIT_READ = 8 << 10
TEXT_READ = 1 << 20
JSON_READ = 16 << 20
# Opening a file never follows a link or waits on a FIFO (both are checked by lstat first, and
# these close the race); O_BINARY keeps Windows from translating line ends.
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
OPEN = os.O_RDONLY | NOFOLLOW | sum(getattr(os, f, 0) for f in ("O_NONBLOCK", "O_CLOEXEC",
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
    registered: dict     # root -> admin dir, for each worktree common's worktrees/ registers


def read_bounded(path: str, limit: int, follow: bool = False) -> bytes | None:
    """path's bytes when it is a regular file of at most limit bytes, else None (missing, a FIFO,
    a device, a dir, a link unless follow, past limit, unreadable). It can't block or read
    without bound: lstat (stat with follow) turns away all but a regular file before the open,
    the open neither follows a link nor waits on a FIFO swapped in since, fstat checks again, and
    the read stops at limit + 1 bytes whatever the size says (a /proc file says 0)."""
    try:
        if not stat.S_ISREG(os.stat(path, follow_symlinks=follow).st_mode):
            return None
        fd = os.open(path, OPEN & ~NOFOLLOW if follow else OPEN)
    except (OSError, ValueError):  # ValueError: a NUL in the path
        return None
    chunks, left = [], limit + 1
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            return None
        while left > 0:
            chunk = os.read(fd, min(CHUNK, left))
            if not chunk:
                break
            chunks.append(chunk)
            left -= len(chunk)
    except OSError:
        return None
    finally:
        os.close(fd)
    return b"".join(chunks) if left > 0 else None


def read_text(path: str, limit: int, follow: bool = False) -> str | None:
    """read_bounded's bytes as UTF-8; None for those it reads as absent and for other bytes."""
    data = read_bounded(path, limit, follow)
    try:
        return None if data is None else data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def read_json(path: str, limit: int):
    """The JSON value in path, None when read_text reads it as absent or it isn't JSON (nested
    past the recursion limit included: json raises RecursionError there, not ValueError)."""
    text = read_text(path, limit)
    try:
        return None if text is None else json.loads(text)
    except (ValueError, RecursionError):
        return None


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


def git_line(path: str) -> str | None:
    """One of git's metadata files (a .git file, an admin dir's gitdir, HEAD or commondir),
    stripped; None when read_text reads it as absent or it holds a NUL (no path can, and
    realpath raises on one)."""
    text = read_text(path, GIT_READ)
    return None if text is None or "\0" in text else text.strip()


def git_path(admin: str, name: str) -> str | None:
    """The path admin/name holds (a gitdir or commondir file), resolved against admin."""
    line = git_line(os.path.join(admin, name))
    return None if line is None else os.path.realpath(os.path.join(admin, line))


def gitdir_file(root: str) -> str | None:
    """The dir root/.git names when it is a file (a linked worktree's, a submodule's), resolved."""
    line = git_line(os.path.join(root, ".git"))
    if line is None or not line.startswith("gitdir:"):
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
    back = git_path(admin, "gitdir")
    if back is None:
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
        back = git_path(admin, "gitdir")
        if back is not None and os.path.basename(back) == ".git":
            out.setdefault(os.path.dirname(back), admin)
    return out


def run_at(repo_dir: str, p: Places) -> Run:
    me = os.path.realpath(repo_dir)
    common = common_dir(me)
    return Run(me, common, os.path.dirname(common) if common else me, lanes_root(common, p),
               registered(common))


def branch(wt: Worktree) -> str:
    head = git_line(os.path.join(wt.admin, "HEAD"))
    if head is None:
        return "?"
    ref = "ref: refs/heads/"
    return head[len(ref):] if head.startswith(ref) else f"detached at {head[:12]}"


def dotclaude(root: str) -> bool:
    """root is a dotclaude checkout: both DOTCLAUDE files sit at it."""
    return all(os.path.isfile(os.path.join(root, f)) for f in DOTCLAUDE)


def lane_of(wt: Worktree, common: str | None) -> bool:
    """wt is a lane of the repo whose git common dir is common, by its own .git file."""
    return common is not None and common_dir(wt.root) == common


def under_lanes(wt: Worktree, run: Run) -> bool:
    """wt sits under run's lanes root, which the lanes config in the state dir names and
    sandboxed Bash can't write: a lane of run's repo whatever its .git file names, and whether
    or not run's .git/worktrees/ still registers it (a lane can delete its own entry there)."""
    return run.lanes is not None and inside(wt.root, run.lanes)


def ours(wt: Worktree, run: Run) -> bool:
    """wt is a lane of run's repo, for the prune: its own .git file says so (lane_of), or run's
    .git/worktrees/ registers it or it sits under run's lanes root (as holders reads it, so the
    main whose run releases a lane whose .git file names a fake admin also prunes its links), and
    it is a dotclaude checkout (so an entry planted there naming another project's worktree
    prunes nothing in it)."""
    return lane_of(wt, run.common) or ((wt.root in run.registered or under_lanes(wt, run))
                                       and dotclaude(wt.root))


def holders(repo_dir: str, env=None) -> list[dict]:
    """Each live lane other than repo_dir that managed links point into, by root: {"root",
    "main", "branch", "links"}, links as `~/.claude/hooks/x.sh -> <target>`. A lane is a linked
    worktree of this repo, or a dotclaude checkout's (both DOTCLAUDE files at its root), so a
    plain clone elsewhere is still refused while the real repo's lane holds. Another project's
    worktree never holds, nor does one inside repo_dir's main checkout. A holder this repo's own
    .git/worktrees/ registers gets this repo's main and its admin dir there, whatever its .git
    file names; one under this repo's lanes root (under_lanes) gets this repo's main too."""
    p = places(env)
    run = run_at(repo_dir, p)
    found = {}
    for link in links(p):
        wt = worktree_at(link.target)
        if (wt is None or wt.root == run.me or inside(wt.root, run.main)
                or not managed(os.path.relpath(link.target, wt.root))
                or not (lane_of(wt, run.common) or dotclaude(wt.root))):
            continue
        if wt.root in run.registered:
            wt = Worktree(wt.root, run.main, run.registered[wt.root])
        elif under_lanes(wt, run):
            wt = Worktree(wt.root, run.main, wt.admin)
        found.setdefault(wt, []).append(show(link, p))
    return [{"root": wt.root, "main": wt.main, "branch": branch(wt), "links": shown}
            for wt, shown in sorted(found.items())]


def hold(repo_dir: str, env=None) -> tuple[list[dict], list[dict]]:
    """(the holders a run from repo_dir must not replace, the ones it releases). A run from a
    holder's main checkout relinks everything, so it releases that holder: one whose .git file
    names it, any its own .git/worktrees/ registers, or any under its lanes root, so a lane
    that deletes its entry there and names a fake admin in its .git file still can't hold this
    main off. Only a main checkout (a real .git dir) releases: a lane whose own .git file names a
    common dir it planted would otherwise read its run as main and release a sibling.

    A known limit, accepted: a lane can write this repo's .git/worktrees/, so an entry planted
    there naming another clone's dotclaude lane makes this main's run release that lane's hold
    (and its prune remove that lane's managed links). Trusting only the holder's own .git file
    instead would let a lane name a fake admin there and hold this main off for good. The effect
    equals an install from this main, which the lead may run anyway, and nothing outside a
    dotclaude checkout is ever pruned."""
    me = os.path.realpath(repo_dir)
    dotgit = os.path.join(me, ".git")
    main = os.path.isdir(dotgit) and not os.path.islink(dotgit)
    held, released = [], []
    for h in holders(repo_dir, env):
        (released if main and h["main"] == me else held).append(h)
    return held, released


def tmux_block(path: str) -> list[str]:
    """The lines inside ~/.tmux.conf's setup-tmux.sh block (to its end marker, or the file's).
    It may be a dotfile manager's link (setup-tmux.sh writes through one), so this read alone
    follows a link: still only to a regular file within TEXT_READ."""
    text = read_text(path, TEXT_READ, follow=True)
    lines = text.splitlines() if text is not None else []
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
        if any(os.path.isabs(w) and "\0" not in w and inside(pointed(w), root) for w in words):
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
        os.lstat(os.path.join(gitdir, "commondir"))
    except FileNotFoundError:  # no commondir: gitdir is the common dir
        return gitdir
    except OSError:
        return None
    return git_path(gitdir, "commondir")


def config_value(text: str, key: str) -> str | None:
    """The string value of `key` in a lanes config. `lane init` writes flat `key = "value"`
    lines, so where tomllib is missing (before 3.11) a regex reads the same value."""
    try:
        import tomllib  # here, not at the top: this module must import on Python 3.10
    except ImportError:  # a basic string unescaped, or a literal one ('...', no escapes) as is
        quoted = r'''(?:"((?:[^"\\]|\\.)*)"|'([^'\n]*)')'''
        m = re.search(rf"^{re.escape(key)}\s*=\s*{quoted}\s*(?:#.*)?$", text, re.M)
        if not m:
            return None
        if m.group(2) is not None:
            return m.group(2)
        return re.sub(r"\\(.)", lambda e: {"n": "\n", "t": "\t"}.get(e.group(1), e.group(1)),
                      m.group(1))
    try:
        value = tomllib.loads(text).get(key)
    except (tomllib.TOMLDecodeError, RecursionError):  # RecursionError: nested past the limit
        return None
    return value if isinstance(value, str) else None


def lanes_config(common: str | None, p: Places) -> str | None:
    """The text of the lanes config `lane init` wrote for the repo whose git common dir is common
    (lanelib.Repo.config_path); None without one."""
    if common is None:
        return None
    key = hashlib.sha256(common.encode()).hexdigest()[:12]
    name = f"{os.path.basename(os.path.dirname(common))}-{key}.toml"
    return read_text(os.path.join(p.state, "lanes", name), TEXT_READ)


def lanes_root(common: str | None, p: Places) -> str | None:
    """The lanes root of the repo whose git common dir is common, from its lanes config; None
    without one."""
    text = lanes_config(common, p)
    root = config_value(text, "root") if text is not None else None
    return os.path.realpath(root) if root and os.path.isabs(root) and "\0" not in root else None


def base_ref(common: str | None, p: Places) -> tuple[str, str]:
    """(the lanes config's base as written, as a full ref), origin/main by default. A short base
    becomes refs/remotes/<base>, as `lane`'s base_ref has it: a tag or branch of that name,
    which sandboxed Bash can make, would otherwise win."""
    text = lanes_config(common, p)
    base = (config_value(text, "base") if text is not None else None) or "origin/main"
    return base, base if base.startswith("refs/") else f"refs/remotes/{base}"


def commits_past(checkout: str, ref: str, env) -> tuple[int | None, str]:
    """(how many commits checkout's HEAD has that ref lacks, ""), or (None, why git couldn't
    tell). git reads objects only (rev-list: no index, no hook), with every transport refused
    (GIT_ALLOW_PROTOCOL=none, so not even a partial clone's lazy fetch runs a program), no GIT_*
    variable from the environment, no system config, no global config (git 2.32 and later),
    its output captured (so no pager), and stops after GIT_WAIT.

    safe.directory is `*` for this call: the global config that would hold the user's entry is
    skipped, and an ownership check adds nothing here, since the run is this checkout's own
    setup.sh, already running its code."""
    import subprocess  # here, not at the top: on Linux it imports fcntl, which git-bash lacks
    genv = {k: v for k, v in env.items() if not k.startswith("GIT_")}
    genv.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0",
                GIT_ALLOW_PROTOCOL="none", GIT_NO_LAZY_FETCH="1", LC_ALL="C")
    try:
        r = subprocess.run(["git", "--no-pager", "-c", "safe.directory=*", "-C", checkout,
                            "rev-list", "--count", "--end-of-options", f"{ref}..HEAD"],
                           env=genv, capture_output=True, text=True, errors="replace",
                           timeout=GIT_WAIT)
    except FileNotFoundError:
        return None, "git not found"
    except subprocess.TimeoutExpired:
        return None, f"git took over {GIT_WAIT} s"
    except (OSError, ValueError) as e:  # ValueError: a NUL in the ref
        return None, f"git didn't run: {e}"
    count = r.stdout.strip()
    if r.returncode == 0 and count.isdigit():
        return int(count), ""
    return None, next(iter(r.stderr.strip().splitlines()), f"git exit {r.returncode}")


def merged_refusal(repo_dir: str, env=None) -> str | None:
    """The line refusing a run from a lane worktree with no commit past the lanes config's base:
    its work is merged (or there is none yet), so its install would take the live install back
    from main for nothing. A rerun that followed a hint printed while that lane held the install
    did just that, 3 s after the lead's reinstall from main released it (2026-10-15). None for
    any other run. It fails closed: when git can't tell, the line says why.

    Only a live linked worktree is checked, and git runs only once the bounded reads have read
    its HEAD and commondir (a FIFO there would hold git to its timeout): so only in a lane's own
    run, never on a lane's files from another run. It guards against a mistake, not a hostile
    lane, which could move the ref or edit its own copy of this file."""
    env = os.environ if env is None else env
    me = os.path.realpath(repo_dir)
    wt = linked_worktree(me)
    if wt is None:
        return None
    common, head = common_dir(me), branch(wt)
    base, ref = base_ref(common, places(env))
    # branch() gives a detached HEAD as "detached at <sha>"; a branch name holds no space.
    label = head if head.startswith("detached at ") else f"branch {head}"
    where = f"the lane worktree {me} ({label})"
    if common is None or head == "?":
        count, why = None, "its HEAD or commondir file doesn't read as git's"
    else:
        count, why = commits_past(me, ref, env)
    if count is None:
        return (f"!!  can't tell whether {where} has a commit past {base} ({why}), and a merged "
                "lane must not take the install back from main. Install from the main checkout "
                f"{wt.main}, or fix that and rerun.\n")
    if count:
        return None
    return (f"!!  {where} has no commit past {base} (merged, or nothing committed yet), so an "
            "install from here would point the live install at work main already has. Install "
            f"from the main checkout {wt.main}, or commit the change here first.\n")


def stale(link: Link, run: Run) -> bool:
    """A managed link this run should remove: into a live lane of this repo (see ours) other
    than run.me and outside run.main, or dangling under an agent worktree in run.main, under
    run.me or under a lane in the lanes root. A link into another repo's worktree is never stale
    here, unless it is a dotclaude checkout run's own .git/worktrees/ registers (hold's limit)."""
    wt = worktree_at(link.target)
    if wt and wt.root != run.me and not inside(wt.root, run.main) and ours(wt, run):
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
    data = read_json(manifest, TEXT_READ)
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
    data = read_json(os.path.join(p.claude, "plugins", "installed_plugins.json"), JSON_READ)
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
    old = read_json(path, JSON_READ)
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
        merged = merged_refusal(args[0])
        if merged:
            sys.stderr.write(merged)
        if held or merged:
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
