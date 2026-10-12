"""Shared core for lanes: repo and lane resolution, records, the lock and the relative-identity lint.

Used by the `lane` CLI (beside this file), hooks/lane_identity.py, hooks/lane_guard.py and
skills/handoff/scripts/handoff-check, each of which puts this directory on sys.path through its
own real path. Stdlib only. docs/lanes.md has the design.

Layout (PLAN.md "Layout"):
  <lane>/.lane/                 the lane's prose: STATUS.md (templates/LANE.md), PLAN.md, artifacts/
  <common-dir>/lanes/           CLI-owned: .lock, <id>/lane.json, <id>/mirror/, _closed/,
                                _locks/<name> (`lane lock`)
  <state-dir>/lanes/<repo>-<hash>.toml
                                the config, written only by a bare `lane init`: `new` and `adopt`
                                run its `setup` sandbox-off, so it lives where sandboxed Bash
                                can't write (state_dir())
"""
import contextlib
import datetime
import fcntl
import glob
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
import tomllib

LANES = "lanes"
RECORD_DIR = ".lane"
CLOSED = "_closed"
LOCKS = "_locks"  # the leading '_' keeps it clear of every lane id, and of Repo.lanes()
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+-]{0,199}")
SHA_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
CLAIM_RE = re.compile(r"#?[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

# The relative-identity lint, shared by the guard and handoff-check. Kept tight on purpose: each
# phrase names a session or lane only relative to the writer, which a reader in another lane
# resolves to itself or to the wrong peer (docs/lanes.md, the 2026-10-11 incident).
RELATIVE = re.compile(
    r"\b(?:(?:an)?other\s+(?:claude\s+)?session|this\s+session|the\s+other\s+(?:lane|session)"
    r"|my\s+(?:lane|session))\b", re.IGNORECASE)
RELATIVE_HINT = ("Write the lane id instead (`lane whoami`, `lane who #<n>`), or the session id; a "
                 "relative name reads as someone else in every other lane.")


def relative_phrases(text: str) -> list[str]:
    """The relative-identity phrases in text, lowercased, with spacing normalized."""
    return [" ".join(m.group(0).lower().split()) for m in RELATIVE.finditer(text or "")]


FENCE = re.compile(r"\s{0,3}(`{3,}|~{3,})")


def prose_only(text: str) -> str:
    """text without HTML comments, fenced code blocks and inline code: what quotes an example
    rather than claiming anything. The one lint the guard and handoff-check share.

    A fence opens with 3+ backticks or tildes and closes on a line of the same char, at least as
    long, with nothing after but whitespace. An unclosed fence runs to the end of the text, which
    errs toward passing quoted text, never toward denying prose."""
    text = re.sub(r"<!--.*?-->", " ", text or "", flags=re.DOTALL)
    kept, fence = [], None
    for line in text.splitlines():
        m = FENCE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)
            else:
                kept.append(line)
        elif m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) \
                and not line[m.end():].strip():
            fence = None
    return re.sub(r"`[^`\n]*`", " ", "\n".join(kept))


def added_phrases(old: str, new: str) -> list[str]:
    """The relative phrases new carries beyond those old already had (an Edit keeping one passes)."""
    left = relative_phrases(old)
    added = []
    for p in relative_phrases(new):
        if p in left:
            left.remove(p)
        else:
            added.append(p)
    return added


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def parse_iso(stamp) -> float | None:
    try:
        return datetime.datetime.fromisoformat(stamp).timestamp()
    except (TypeError, ValueError):
        return None


def git(args: list[str],
    cwd: str,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Run git with C-locale output; check raises CalledProcessError on a non-zero exit."""
    env = dict(os.environ, LC_ALL="C", GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env,
                          check=check, timeout=60)


def state_dir() -> str:
    """$XDG_STATE_HOME/dotclaude: readable but not writable from the Bash sandbox, and denied to
    delegated agents (policy.toml's {state_dir})."""
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                        "dotclaude")


class Repo:
    """Where a directory sits: its checkout, the shared common dir and the main checkout."""

    def __init__(self, toplevel: str, common_dir: str):
        self.toplevel = os.path.realpath(toplevel)
        self.common_dir = os.path.realpath(common_dir)
        self.main = os.path.dirname(self.common_dir)  # toplevel == this means the main checkout
        self.lanes_dir = os.path.join(self.common_dir, LANES)
        self.rejected: list[tuple[str, str]] = []  # filled by lanes()

    @property
    def is_main(self) -> bool:
        return self.toplevel == self.main

    @property
    def config_path(self) -> str:
        """Out of the repo, where sandboxed Bash can't write (docs/lanes.md S3). One file per
        common dir."""
        key = hashlib.sha256(self.common_dir.encode()).hexdigest()[:12]
        return os.path.join(state_dir(), LANES, f"{os.path.basename(self.main)}-{key}.toml")

    @property
    def has_lanes(self) -> bool:
        """A lanes repo: `lane init` wrote its config."""
        return os.path.isfile(self.config_path)

    def check_lanes_dir(self) -> None:
        """A linked <common-dir>/lanes would carry every lanes write (the lock, records, the
        mirror, archives) wherever it points."""
        if os.path.islink(self.lanes_dir):
            raise Untrusted(f"{self.lanes_dir} is a symlink")

    def lanes(self, shared: bool = False) -> list[dict]:
        """Every registered (not closed) lane's lane.json that passes record_problem, sorted by
        id. Records that fail, and every record of a path two records claim, are left out and
        listed in self.rejected as (id, why). shared=True keeps the latter: neither may name a
        session's lane or be acted in, but each still holds its claims, port and cap slot, or a
        planted twin would void the real lane's claims."""
        out, self.rejected = [], []
        if os.path.islink(self.lanes_dir):
            self.rejected.append(("*", f"{self.lanes_dir} is a symlink"))
            return out
        for path in sorted(glob.glob(os.path.join(self.lanes_dir, "*", "lane.json"))):
            lane_id = os.path.basename(os.path.dirname(path))
            if lane_id.startswith("_"):
                continue
            try:
                out.append(read_record(self, lane_id))
            except Untrusted as e:
                self.rejected.append((lane_id, str(e)))
            except OSError:
                continue
        seen = {}
        for lane in out:
            seen.setdefault(os.path.realpath(lane["path"]), []).append(lane["id"])
        twins = {p: ids for p, ids in seen.items() if len(ids) > 1}
        for p, ids in twins.items():
            self.rejected += [(i, f"shares its path {p} with {', '.join(ids)}") for i in ids]
        return out if shared else [lane for lane in out
                                   if os.path.realpath(lane["path"]) not in twins]

    def lane_at(self, toplevel: str, lanes: list[dict] | None = None) -> dict | None:
        top = os.path.realpath(toplevel)
        for lane in self.lanes() if lanes is None else lanes:
            if os.path.realpath(lane.get("path") or "") == top:
                return lane
        return None

    def identity(self, lanes: list[dict] | None = None) -> tuple[str, dict | None]:
        """("lane", lane) | ("main", None) | ("unregistered", None) | ("plain", None)."""
        if not self.has_lanes:
            return "plain", None
        lane = self.lane_at(self.toplevel, lanes)
        if lane:
            return "lane", lane
        return ("main", None) if self.is_main else ("unregistered", None)

    def config(self) -> dict:
        with open(self.config_path, "rb") as f:
            return tomllib.load(f)

    def lane_dir(self, lane_id: str) -> str:
        return os.path.join(self.lanes_dir, lane_id)

    def lane_json(self, lane_id: str) -> str:
        return os.path.join(self.lane_dir(lane_id), "lane.json")


def resolve(cwd: str) -> Repo | None:
    """The Repo holding cwd, or None outside a work tree (or when git fails)."""
    try:
        p = git(["rev-parse", "--path-format=absolute", "--git-common-dir", "--show-toplevel"], cwd)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = p.stdout.splitlines()
    if p.returncode != 0 or len(lines) != 2:
        return None
    return Repo(lines[1], lines[0])


def resolve_path(path: str) -> Repo | None:
    """The Repo holding a file path that may not exist yet: resolved from its nearest existing dir."""
    d = os.path.dirname(os.path.realpath(path))
    while d and not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return resolve(d) if d else None


def common_dir_of(path: str) -> str | None:
    """The git common dir for a path inside a .git dir, where --show-toplevel fails."""
    d = os.path.dirname(os.path.realpath(path))
    while d and not os.path.isdir(d):
        d = os.path.dirname(d)
    try:
        p = git(["rev-parse", "--path-format=absolute", "--git-common-dir"], d)
    except (OSError, subprocess.SubprocessError):
        return None
    return os.path.realpath(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip() else None


def is_live(lane: dict) -> bool:
    """A lane whose worktree still exists. A stale one's claims are void (invariant 3)."""
    return os.path.isdir(lane.get("path") or "")


def record_dir(lane: dict) -> str:
    return os.path.join(lane["path"], RECORD_DIR)


def record_is_link(lane: dict) -> bool:
    """A .lane that is itself a symlink (a repo can commit `.lane -> ..`): following it would
    mirror and archive its whole target, so the mirror, `done`, `new` and `adopt` refuse one and
    the guard denies writes through one."""
    return os.path.islink(record_dir(lane))


def record_path(lane: dict) -> str:
    return os.path.join(record_dir(lane), "STATUS.md")


def walk_record(src: str, rel: str = ""):
    """Yield (path, relative path, kind) under src, kind 'dir', 'file' or 'link'. A symlink is
    never followed, to a file or a dir, dangling or not: following one copied whatever it reached
    (`../..`, a home dir, its keys) into the mirror and every archive. Evidence is real files."""
    for entry in sorted(os.scandir(src), key=lambda e: e.name):
        path, sub = entry.path, os.path.join(rel, entry.name)
        if entry.is_symlink():
            yield path, sub, "link"
        elif entry.is_dir(follow_symlinks=False):
            yield path, sub, "dir"
            yield from walk_record(path, sub)
        else:
            yield path, sub, "file"


def copy_record(src: str, dest: str) -> None:
    """Copy a record dir (a lane's .lane/) to dest, which must not exist; links stay links."""
    os.makedirs(dest)
    for path, rel, kind in walk_record(src):
        target = os.path.join(dest, rel)
        if kind == "dir":
            os.makedirs(target, exist_ok=True)
        elif kind == "link":
            os.symlink(os.readlink(path), target)
        else:
            shutil.copy2(path, target)


def newest_mtime(src: str) -> float:
    """The latest mtime under src, dirs included (a deletion touches its dir), by lstat: a link's
    own change counts, never its target's."""
    newest = os.lstat(src).st_mtime
    for path, _, _ in walk_record(src):
        newest = max(newest, os.lstat(path).st_mtime)
    return newest


def mirror_dir(repo: "Repo",
    lane_id: str,
    *,
    restore: bool,
) -> str | None:
    """lanes/<id>/mirror, the copy of a lane's .lane/ that outlives its worktree, or None. A hook
    killed between its two renames leaves only mirror.old, the only copy, so no reader may miss
    it. restore=True puts it back as mirror, and only a caller holding the lanes lock (the hook,
    `done`) may ask, or it races the hook's swap; lock-free readers get mirror.old in place."""
    dest = os.path.join(repo.lane_dir(lane_id), "mirror")
    old = dest + ".old"

    def real_dir(p):  # a planted link here would have `done` archive whatever it points at
        return os.path.isdir(p) and not os.path.islink(p)

    if real_dir(dest):
        return dest
    if not real_dir(old):
        return None
    if restore:
        os.rename(old, dest)
        return dest
    return old


def write_json(path: str, data) -> None:
    """Atomic write: a temp file in the same dir, fsynced, then renamed over path."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def write_text(path: str, text: str) -> None:
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


class LockTimeout(Exception):
    pass


@contextlib.contextmanager
def lock(repo: Repo, timeout: float | None = None):
    """flock on <common-dir>/lanes/.lock: every write to lanes data happens under it. timeout None
    blocks; a number raises LockTimeout after that many seconds (hooks use one)."""
    repo.check_lanes_dir()
    os.makedirs(repo.lanes_dir, exist_ok=True)
    with open(os.path.join(repo.lanes_dir, ".lock"), "a") as f:
        if timeout is None:
            fcntl.flock(f, fcntl.LOCK_EX)
        else:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LockTimeout(repo.lanes_dir)
                    time.sleep(0.05)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def update_lane(repo: Repo, lane_id: str, change) -> dict:
    """Read lane.json (checked: read_record), apply change(lane) in place, stamp updated, write
    it back. Call under lock."""
    path = repo.lane_json(lane_id)
    lane = read_record(repo, lane_id)
    change(lane)
    lane["updated"] = now_iso()
    write_json(path, lane)
    return lane


def valid_id(lane_id: str) -> bool:
    """A lane id is a slug: no path separator, no '..', no leading '_' (that is _closed)."""
    return (isinstance(lane_id, str) and bool(ID_RE.fullmatch(lane_id)) and ".." not in lane_id
            and lane_id != "main")


def valid_branch(name) -> bool:
    """A branch name safe to hand git as an argument: it starts with a letter or digit, never
    '-' (git would read `--output=<file>` as an option and overwrite that file), from a plain
    charset, with none of the forms git refuses."""
    return (isinstance(name, str) and bool(BRANCH_RE.fullmatch(name)) and ".." not in name
            and "//" not in name and "/." not in name and not name.endswith((".lock", "/", ".")))


class Untrusted(ValueError):
    """A lanes file that sandboxed Bash could have planted, refused before sandbox-off code acts
    on it."""


def record_problem(lane, lane_id: str) -> str | None:
    """Why a lane.json can't be trusted, or None. Sandboxed Bash can write every lane.json (the
    sandboxed `claim` and `note` do), and sandbox-off code (the hooks, `ls`, `open`, `done`,
    `new`, `adopt`) acts on its fields: the id becomes a path, the branch a git argument, the
    path a cwd. So each field is checked at load, and a record that fails is never used."""
    if not isinstance(lane, dict):
        return "not a JSON object"
    if lane.get("id") != lane_id or not valid_id(lane_id):
        return f"its id {lane.get('id')!r} is not its dir name"
    if not valid_branch(lane.get("branch")):
        return f"bad branch {lane.get('branch')!r}"
    path = lane.get("path")
    if not isinstance(path, str) or not os.path.isabs(path) or os.path.normpath(path) != path:
        return f"bad path {path!r}"
    sha = lane.get("base_sha")
    if sha is not None and not (isinstance(sha, str) and SHA_RE.fullmatch(sha)):
        return f"bad base_sha {sha!r}"
    port = lane.get("port")
    if port is not None and (type(port) is not int or not 0 < port < 65536):
        return f"bad port {port!r}"
    claims = lane.get("claims", [])
    if not isinstance(claims, list) or not all(isinstance(c, str) and CLAIM_RE.fullmatch(c)
                                               for c in claims):
        return f"bad claims {claims!r}"
    sessions = lane.get("sessions", [])
    if not isinstance(sessions, list) or not all(isinstance(s, dict) for s in sessions):
        return "bad sessions"
    return None


def read_record(repo: "Repo", lane_id: str) -> dict:
    """lanes/<id>/lane.json, checked (record_problem); a linked lanes dir or <id> dir is refused,
    since a write under it would land wherever the link points. FileNotFoundError when absent."""
    repo.check_lanes_dir()
    if not valid_id(lane_id) or os.path.islink(repo.lane_dir(lane_id)):
        raise Untrusted(f"lanes/{lane_id} is not a lane dir")
    with open(repo.lane_json(lane_id)) as f:
        try:
            lane = json.load(f)
        except ValueError:
            raise Untrusted(f"lanes/{lane_id}/lane.json is not JSON")
    if why := record_problem(lane, lane_id):
        raise Untrusted(f"lanes/{lane_id}/lane.json: {why}")
    return lane


def worktree_problem(repo: "Repo", path: str, lanes: list[dict]) -> str | None:
    """Why sandbox-off code must not act in path (a lane's cwd for `open` and the setup, the
    copy's destination, what `done` archives and removes), or None. Sandboxed Bash can write a
    lane.json's path, the main checkout and git's worktree list, so a path must be a real
    worktree of this repo (its .git file points into <common-dir>/worktrees/ and back), outside
    the main checkout and the common dir, and not inside another lane: else a planted dir with
    its own .claude/ config would get a sandbox-off `claude` or setup."""
    real = os.path.realpath(path)
    if real != path:
        return f"{path} is reached through a symlink"
    if inside(real, repo.main) or inside(real, repo.common_dir):
        return f"{path} is inside the main checkout"
    for other in lanes:
        if other["path"] != real and inside(real, other["path"]):
            return f"{path} is inside lane {other['id']}"
    dotgit = os.path.join(real, ".git")
    try:
        if not stat.S_ISREG(os.lstat(dotgit).st_mode):
            return f"{dotgit} is not a worktree's .git file"
        with open(dotgit) as f:
            gitdir = f.read().strip().removeprefix("gitdir: ")
        admin = os.path.realpath(os.path.join(real, gitdir))
        with open(os.path.join(admin, "gitdir")) as f:
            back = os.path.realpath(f.read().strip())
    except OSError as e:
        return f"{path} is not a worktree ({e.strerror})"
    if os.path.dirname(admin) != os.path.join(repo.common_dir, "worktrees") or back != dotgit:
        return f"{path} is not a worktree of this repo"
    return None


def norm_request(req: str) -> str:
    """'42' or '#42' -> '#42'; anything else is kept as given (a tracker key like ABC-7)."""
    req = req.strip()
    return "#" + req if req.isdigit() else req


def section(text: str,
    *names: str,
    prefixes: tuple[str, ...] = (),
) -> str | None:
    """The body of the first `## <heading>` section whose heading equals one of names or starts
    with one of prefixes (case-insensitive), with HTML comments and template placeholder lines
    (`- <...>`) removed. None when no such heading exists."""
    lines = (text or "").splitlines()
    wanted = {n.lower() for n in names}
    starts = tuple(p.lower() for p in prefixes)
    for i, line in enumerate(lines):
        m = re.match(r"##\s+(.+?)\s*$", line)
        heading = m.group(1).lower() if m else ""
        if not m or not (heading in wanted or (starts and heading.startswith(starts))):
            continue
        body = []
        for nxt in lines[i + 1:]:
            if re.match(r"#{1,2}\s", nxt):
                break
            body.append(nxt)
        cleaned = re.sub(r"<!--.*?-->", "", "\n".join(body), flags=re.DOTALL)
        kept = [ln for ln in cleaned.splitlines()
                if ln.strip() and not re.fullmatch(r"\s*(?:[-*]\s*)?<[^<>]*>\s*", ln)]
        return "\n".join(kept)
    return None


def next_block(text: str) -> str | None:
    """The status file's Next block: the first `## Next...` (or `## Notes for next session`)
    section, as section() cleans it."""
    return section(text, "Notes for next session", prefixes=("next",))


def status_path(repo: Repo, lane: dict | None) -> str:
    """The status file a handoff writes: the lane record in a lane, else the root STATUS.md."""
    return record_path(lane) if lane else os.path.join(repo.toplevel, "STATUS.md")


APPROVED, MALFORMED, UNAPPROVED, STALE = "approved", "malformed", "unapproved", "stale"
APPROVAL_OPEN = re.compile(r"\(approved by Hayden", re.IGNORECASE)
APPROVAL_DATE = re.compile(r" (\d{4}-\d{2}-\d{2})\)")
BULLET = re.compile(r"\s*(?:[-*+]|\d+[.)])\s")


def first_item(block: str | None) -> str:
    """The Next block's first item: its first non-empty line (a bullet or not) with the wrapped
    continuation lines after it, up to the next bullet at any depth. A nested bullet is a step
    of its own, so it ends the item too."""
    lines = [ln for ln in (block or "").splitlines() if ln.strip()]
    item = lines[:1]
    for ln in lines[1:]:
        if BULLET.match(ln):
            break
        item.append(ln)
    return "\n".join(item)


def approval(block: str | None, since: datetime.date | None = None) -> str:
    """Whether a Next block pre-approves its next step, for /pass's resume mode. MALFORMED when
    any `(approved by Hayden` in the block lacks a real ISO date (the handoff skill writes the
    marker only for an approval given in the session, citing its date). Otherwise only a marker
    on the first item (first_item) counts, since an approval covers one step: APPROVED when it
    carries `(approved by Hayden YYYY-MM-DD)`, STALE when a first-item marker is dated before
    `since` (the session's start date, local time: the approval came from an earlier session),
    UNAPPROVED when the first item has no marker. A marker on a later item is ignored."""
    for m in APPROVAL_OPEN.finditer(block or ""):
        date = APPROVAL_DATE.match(block, m.end())
        try:
            datetime.date.fromisoformat(date.group(1) if date else "")
        except ValueError:
            return MALFORMED
    first = first_item(block)
    dates = [datetime.date.fromisoformat(APPROVAL_DATE.match(first, m.end()).group(1))
             for m in APPROVAL_OPEN.finditer(first)]
    if not dates:
        return UNAPPROVED
    return STALE if since is not None and min(dates) < since else APPROVED


def sessions_dir() -> str:
    return os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"),
                        "sessions")


SANDBOX_INITS = {"apply-seccomp", "bwrap"}


def sandboxed(proc: str = "/proc") -> bool:
    """Whether this process runs in the Bash sandbox, by its pid namespace's pid 1: there it is
    the sandbox's own launcher (cmdline argv0 `apply-seccomp`, measured on Claude Code 2.1.296,
    whose comm can read `3`), outside it is init. CLAUDE_PID can't tell: it is set in both."""
    names = set()
    try:
        with open(os.path.join(proc, "1", "cmdline"), "rb") as f:
            names.add(os.path.basename(f.read().split(b"\0")[0].decode(errors="replace")))
    except OSError:
        pass
    try:
        with open(os.path.join(proc, "1", "comm")) as f:
            names.add(f.read().strip())
    except OSError:
        pass
    return bool(names & SANDBOX_INITS)


def pids_visible(proc: str = "/proc") -> bool:
    """False inside the Bash sandbox: each sandboxed command runs in its own pid namespace, so
    other processes, the sessions in a lane among them, have no /proc entry. SANDBOX_RUNTIME=1,
    set only inside, says so too (as delegation_common.pids_visible reads it)."""
    forced = os.environ.get("_LANE_TEST_SANDBOXED")  # tests/lanes only; they may run sandboxed
    if forced in ("0", "1"):
        return forced == "0"
    return os.environ.get("SANDBOX_RUNTIME") != "1" and not sandboxed(proc)


def live_sessions() -> list[dict] | None:
    """Claude Code's per-process session files whose pid is alive; None when pids can't be seen."""
    if not pids_visible():
        return None
    out = []
    for path in glob.glob(os.path.join(sessions_dir(), "*.json")):
        try:
            with open(path) as f:
                s = json.load(f)
        except (OSError, ValueError):
            continue
        pid = s.get("pid") if isinstance(s, dict) else None
        if isinstance(pid, int) and os.path.exists(f"/proc/{pid}"):
            out.append(s)
    return out


def inside(path: str, root: str) -> bool:
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)
