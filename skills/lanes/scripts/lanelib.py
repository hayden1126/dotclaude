"""Shared core for lanes: repo and lane resolution, records, the lock and the relative-identity lint.

Used by the `lane` CLI (beside this file), hooks/lane_identity.py, hooks/lane_guard.py and
skills/handoff/scripts/handoff-check, each of which puts this directory on sys.path through its
own real path. Stdlib only. docs/lanes.md has the design.

Layout (PLAN.md "Layout"):
  <lane>/.lane/                 the lane's prose: STATUS.md (templates/LANE.md), PLAN.md, artifacts/
  <common-dir>/lanes/           CLI-owned: config.toml, .lock, <id>/lane.json, <id>/mirror/, _closed/
"""
import contextlib
import datetime
import fcntl
import glob
import json
import os
import re
import subprocess
import tempfile
import time
import tomllib

LANES = "lanes"
RECORD_DIR = ".lane"
CLOSED = "_closed"
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

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


class Repo:
    """Where a directory sits: its checkout, the shared common dir and the main checkout."""

    def __init__(self, toplevel: str, common_dir: str):
        self.toplevel = os.path.realpath(toplevel)
        self.common_dir = os.path.realpath(common_dir)
        self.main = os.path.dirname(self.common_dir)  # toplevel == this means the main checkout
        self.lanes_dir = os.path.join(self.common_dir, LANES)

    @property
    def is_main(self) -> bool:
        return self.toplevel == self.main

    @property
    def config_path(self) -> str:
        return os.path.join(self.lanes_dir, "config.toml")

    @property
    def has_lanes(self) -> bool:
        """A lanes repo: `lane init` wrote its config."""
        return os.path.isfile(self.config_path)

    def lanes(self) -> list[dict]:
        """Every registered (not closed) lane's lane.json, sorted by id."""
        out = []
        for path in sorted(glob.glob(os.path.join(self.lanes_dir, "*", "lane.json"))):
            if os.path.basename(os.path.dirname(path)).startswith("_"):
                continue
            try:
                with open(path) as f:
                    lane = json.load(f)
            except (OSError, ValueError):
                continue
            if isinstance(lane, dict) and lane.get("id"):
                out.append(lane)
        return out

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


def record_dir(lane: dict) -> str:
    return os.path.join(lane["path"], RECORD_DIR)


def record_path(lane: dict) -> str:
    return os.path.join(record_dir(lane), "STATUS.md")


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
    """Read lane.json, apply change(lane) in place, stamp updated, write it back. Call under lock."""
    path = repo.lane_json(lane_id)
    with open(path) as f:
        lane = json.load(f)
    change(lane)
    lane["updated"] = now_iso()
    write_json(path, lane)
    return lane


def norm_request(req: str) -> str:
    """'42' or '#42' -> '#42'; anything else is kept as given (a tracker key like ABC-7)."""
    req = req.strip()
    return "#" + req if req.isdigit() else req


def section(text: str, *names: str) -> str | None:
    """The body of the first `## <name>` section present (case-insensitive), with HTML comments
    and template placeholder lines (`- <...>`) removed. None when no such heading exists."""
    lines = (text or "").splitlines()
    wanted = {n.lower() for n in names}
    for i, line in enumerate(lines):
        m = re.match(r"##\s+(.+?)\s*$", line)
        if not m or m.group(1).lower() not in wanted:
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


def sessions_dir() -> str:
    return os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"),
                        "sessions")


def live_sessions() -> list[dict] | None:
    """Claude Code's per-process session files whose pid is alive; None when pids can't be seen
    (a sandboxed command runs in its own pid namespace, so its own claude's /proc entry is gone)."""
    own = os.environ.get("CLAUDE_PID")
    if own and own.isdigit() and not os.path.exists(f"/proc/{own}"):
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
