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
  <state-dir>/lanes/<repo>-<hash>.lead.json
                                the lead record (read_lead): the main-checkout session that last
                                acted as lead, written only by bare commands
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
from typing import NamedTuple

LANES = "lanes"
RECORD_DIR = ".lane"
CLOSED = "_closed"
LOCKS = "_locks"  # the leading '_' keeps it clear of every lane id, and of Repo.lanes()
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
BRANCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+-]{0,199}")
SHA_RE = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")
CLAIM_RE = re.compile(r"#?[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
SID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")  # a session id; hooks/stop_ring.py SID

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
    timeout: float = 60,
) -> subprocess.CompletedProcess:
    """Run git with C-locale output; check raises CalledProcessError on a non-zero exit."""
    env = dict(os.environ, LC_ALL="C", GIT_TERMINAL_PROMPT="0")
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env,
                          check=check, timeout=timeout)


# A plain /pass respawns the pane, which kills every background task with it. So it goes ahead
# only after a Stop that listed no task but these: `dream` is memory upkeep, and an `artifact
# watch` is the live watch the Artifact tool arms on each publish (hooks/stop_ring.py
# artifact_url), a subscription for comments, not work in flight. The model never sees its id,
# so a session can't stop it, and it blocked every plain pass after a publish (incident
# e7cc7b9a, 2026-10-13). The respawn ends it, as quitting would. Teammates and
# monitors count, though stop-ring.sh rings past them (it asks "is the turn waiting on its
# result?", not "would a respawn kill it?"). pass-respawn refuses by this rule, and the autopass
# watcher (hooks/context_watch.py) says "compact mode" by it, so the two never disagree.
PLAIN_PASS_IGNORES = frozenset({"dream", "artifact watch"})


def plain_pass_ignores(entry: dict) -> bool:
    """Whether a plain pass lets the respawn end this task (a task_entries entry): a label
    PLAIN_PASS_IGNORES names, and for an artifact watch its page too. stop_ring writes `url`
    only for a description artifact_url matched, so a type merely spelled `artifact watch`
    still blocks."""
    return entry["label"] in PLAIN_PASS_IGNORES and (entry["label"] != "artifact watch"
                                                     or bool(entry.get("url")))
TASK_FIELDS = ("id", "description", "url")


def task_entries(tasks) -> list[dict] | None:
    """A stop record's `tasks` (or the Stop payload's labels) as entries, {label} plus the
    string fields of TASK_FIELDS it has; None when tasks isn't a list. An entry is a label or an
    object holding one; anything else, or an empty label, is `unlabeled`. Only strings survive:
    the record is data, and its text reaches tmux, the toast and pass.log."""
    if not isinstance(tasks, list):
        return None
    out = []
    for t in tasks:
        label = t if isinstance(t, str) else t.get("label") if isinstance(t, dict) else None
        e = {"label": label if isinstance(label, str) and label else "unlabeled"}
        if isinstance(t, dict):
            e.update({k: t[k] for k in TASK_FIELDS if isinstance(t.get(k), str)})
        out.append(e)
    return out


def plain_pass_blockers(tasks) -> list[dict]:
    """The entries (task_entries) that make a plain pass refuse, in order: every task but those
    plain_pass_ignores lets go. A list that isn't a list blocks, as `?`: with no task list the
    respawn can't be shown safe."""
    entries = task_entries(tasks)
    if entries is None:
        return [{"label": "?"}]
    return [e for e in entries if not plain_pass_ignores(e)]


TASK_NOUNS = {"unlabeled": "unlabeled task", "None": "unlabeled task"}


def describe_task(entry: dict, chars: int) -> str:
    """One task (a task_entries entry) as pass-respawn's refusal, pass.log, --tasks and the
    autopass nudge name it: its noun, then an artifact watch's page or else its description in
    double quotes (cut to chars), then its id in parentheses, each when the record has it:
    'monitor "deploy events" (b0fzd27l4)'."""
    text = TASK_NOUNS.get(entry["label"], entry["label"])
    if url := entry.get("url"):
        text += f" {url[:chars]}"
    elif desc := entry.get("description"):
        text += f' "{desc if len(desc) <= chars else desc[:chars - 3] + "..."}"'
    return text + (f" ({entry['id']})" if entry.get("id") else "")


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
    def lead_path(self) -> str:
        """The lead record (read_lead), beside the config: only a bare command can write it, so
        no lane's sandboxed Bash can make itself the lead. tmux/tmux-tab-bar reads this path."""
        return self.config_path.removesuffix(".toml") + ".lead.json"

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


# What `claude --model` and `--effort` take (Claude Code 2.1.301's --help). `lane init` and
# `lane open` check a model against the aliases strictly: a typo reaches a detached window, where
# claude stays up and shows an API error nobody watches (docs/lanes.md, "Model and effort").
MODEL_ALIASES = ("default", "opus", "sonnet", "haiku", "fable", "opusplan")
# The aliases with a 1M form: default[1m] fails at its first request, and /model says haiku and
# opusplan have none (probed 2026-10-15).
ONE_M = ("opus", "sonnet", "fable")
# The model families (the id's second part, claude-<family>-...) each alias can run as; default
# is the account's own and can run as any.
FAMILIES = {"opus": ("opus",), "sonnet": ("sonnet",), "haiku": ("haiku",), "fable": ("fable",),
            "opusplan": ("opus", "sonnet")}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
MODEL_ID = re.compile(r"claude-[a-z0-9]+(?:[.-][a-z0-9]+)*")  # a full name, as transcripts carry it
MODEL_ALIAS = re.compile(rf"(?:{'|'.join(ONE_M)})(?:\[1m\])?|default|haiku|opusplan")
MODEL_NAME = re.compile(rf"{MODEL_ALIAS.pattern}|{MODEL_ID.pattern}(?:\[1m\])?")
MODEL_SHAPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@\[\]-]{0,99}")  # never a flag, no shell syntax


def model_problem(name) -> str | None:
    """Why name can't be a `lane init` or `lane open` model, or None."""
    if isinstance(name, str) and MODEL_NAME.fullmatch(name):
        return None
    return (f"{name!r} is not a model: give an alias ({', '.join(MODEL_ALIASES)}; "
            f"{', '.join(ONE_M)} also take [1m]) or a full name like claude-sonnet-5-5 or "
            "claude-sonnet-5-5[1m]")


def could_run(name: str, ran: str) -> bool:
    """Whether a session given --model name could have run as ran, a resolved id (MODEL_ID): a
    full name as itself or its dated id (claude-haiku-4-5 runs as claude-haiku-4-5-20251001), an
    alias as an id of its family (FAMILIES). A name of another shape (a Bedrock or Vertex id)
    can't be judged, so it is never contradicted."""
    base = name.removesuffix("[1m]")
    if MODEL_ID.fullmatch(base):
        return bool(re.fullmatch(re.escape(base) + r"(?:-\d{8})?", ran))
    if base == "default" or base not in FAMILIES:
        return True
    return ran.split("-")[1] in FAMILIES[base]


def effort_problem(level) -> str | None:
    """Why level can't be an effort, or None."""
    if level in EFFORTS:
        return None
    return f"{level!r} is not an effort: give one of {', '.join(EFFORTS)}"


def safe_model(name) -> bool:
    """Whether a --model value the old claude launched with can go on to the next one: it already
    ran, so only its shape is checked (it can't read as a flag or carry shell syntax)."""
    return isinstance(name, str) and bool(MODEL_SHAPE.fullmatch(name))


class Untrusted(ValueError):
    """A lanes file that sandboxed Bash could have planted, refused before sandbox-off code acts
    on it."""


def record_problem(lane, lane_id: str) -> str | None:
    """Why a lane.json can't be trusted, or None. Sandboxed Bash can write every lane.json (the
    sandboxed `claim` and `note` do), and sandbox-off code (the hooks, `ls`, `open`, `done`,
    `new`, `adopt`, `addr`) acts on its fields: the id becomes a path, the branch a git argument, the
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
    # Both files read with read_head: the admin dir is wherever the .git file says, so either
    # can be a FIFO a plain open would wait on.
    dotgit = os.path.join(real, ".git")
    text = read_head(dotgit, GITDIR_MAX)
    if text is None:
        return f"{dotgit} is not a worktree's .git file"
    gitdir = text.decode(errors="replace").strip().removeprefix("gitdir: ")
    admin = os.path.realpath(os.path.join(real, gitdir)) if "\0" not in gitdir else ""
    back = read_head(os.path.join(admin, "gitdir"), GITDIR_MAX) if admin else None
    if back is None:
        return f"{path} is not a worktree (its admin dir's gitdir file can't be read)"
    back = back.decode(errors="replace").strip()
    back = os.path.realpath(back) if back and "\0" not in back else ""
    if os.path.dirname(admin) != os.path.join(repo.common_dir, "worktrees") or back != dotgit:
        return f"{path} is not a worktree of this repo"
    # git takes the config (core.fsmonitor runs a command on `git status`) from the dir commondir
    # names, and the admin dir is sandbox-writable: it must name this repo's common dir.
    common = read_head(os.path.join(admin, "commondir"), GITDIR_MAX)
    common = common.decode(errors="replace").strip() if common is not None else ""
    if not common or "\0" in common or (
            os.path.realpath(os.path.join(admin, common)) != os.path.realpath(repo.common_dir)):
        return f"{path} is not a worktree of this repo (its commondir names another git dir)"
    return None


GITDIR_MAX = 4096  # bytes read of a .git file or an admin dir's gitdir file


def linked_worktree(repo: "Repo", cwd) -> str | None:
    """The linked worktree of this repo that holds cwd (a cwd from /proc or a session file), by
    the nearest .git at or above it: a regular file naming <common-dir>/worktrees/<x>, whose
    gitdir file names that .git back. Both are read with read_head: bounded, never through a
    link, never waiting on a FIFO. None for the main checkout (its .git is a dir), for another
    repo's checkout, and for anything else."""
    if not (isinstance(cwd, str) and "\0" not in cwd):
        return None
    top = os.path.realpath(cwd)
    while not os.path.lexists(os.path.join(top, ".git")):
        if (parent := os.path.dirname(top)) == top:
            return None
        top = parent
    dotgit = os.path.join(top, ".git")
    text = (read_head(dotgit, GITDIR_MAX) or b"").decode(errors="replace").strip()
    if not text.startswith("gitdir: ") or "\0" in text:
        return None
    admin = os.path.realpath(os.path.join(top, text[len("gitdir: "):]))
    if os.path.dirname(admin) != os.path.join(repo.common_dir, "worktrees"):
        return None
    back = (read_head(os.path.join(admin, "gitdir"), GITDIR_MAX) or b"").decode(
        errors="replace").strip()
    if not back or "\0" in back or os.path.realpath(os.path.join(admin, back)) != dotgit:
        return None
    return top


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
    """The status file a handoff writes: the lane record in a lane, else the root STATUS.md.
    Built from the toplevel, never lane.json's sandbox-writable `path`: in the session's own lane
    the two name the same file (identity matches them by realpath)."""
    if lane:
        return os.path.join(repo.toplevel, ".lane", "STATUS.md")
    return os.path.join(repo.toplevel, "STATUS.md")


APPROVED, MALFORMED, UNAPPROVED, STALE = "approved", "malformed", "unapproved", "stale"
APPROVAL_OPEN = re.compile(r"\(approved by Hayden", re.IGNORECASE)
APPROVAL_DATE = re.compile(r" (\d{4}-\d{2}-\d{2})\)")
BULLET = re.compile(r"\s*(?:[-*+]|\d+[.)])\s")
# `Keep open: <why>`, `- **Keep open:** <why>`: a lane with more PRs to come after a merge.
# Spaces and tabs only: a match never runs past its own line.
KEEP_OPEN = re.compile(r"[ \t]*(?:(?:[-*+]|\d+[.)])[ \t]+)?[*_`]*keep open[*_`]*[ \t]*:",
                       re.IGNORECASE)


def next_items(block: str | None) -> list[str]:
    """The Next block's items: each a non-empty line (a bullet or not) with the wrapped
    continuation lines after it, up to the next bullet at any depth. A nested bullet is a step
    of its own, so it starts an item too. So does an unindented `Keep open:` line, which only
    indented lines continue (section() has dropped the blank lines): it is never folded into
    the step before it, nor a plain-text step after it into it. An indented plain line is a
    wrapped step, whose text may start with a mention of the flag. So the flag is written on
    one line, or as a bullet whose wrap is indented."""
    items: list[list[str]] = []
    kept = False
    for ln in (block or "").splitlines():
        if not ln.strip():
            continue
        if (not items or BULLET.match(ln) or (KEEP_OPEN.match(ln) and not ln[:1].isspace())
                or (kept and not ln[:1].isspace())):
            items.append([ln])
            kept = bool(KEEP_OPEN.match(ln))
        else:
            items[-1].append(ln)
    return ["\n".join(item) for item in items]


def kept_open(block: str | None) -> str | None:
    """The first `Keep open: <why>` item in the Next block, None without one. A lane with more
    PRs to come starts its Next with it, and `lane done` and `handoff-check --closing` refuse
    the lane while it stands. Any item counts, not only the first: a false hit only holds a
    close, while a miss would end a lane that has work left."""
    return next((item for item in next_items(block) if KEEP_OPEN.match(item)), None)


def first_item(block: str | None) -> str:
    """The Next block's first step (next_items), "" without one. A `Keep open:` item is a flag
    about the lane, not a step, so the step after it counts."""
    return next((item for item in next_items(block) if not KEEP_OPEN.match(item)), "")


def approval_dates(block: str | None) -> list[datetime.date]:
    """The dates of the first item's approval markers (approval checks they parse first)."""
    first = first_item(block)
    return [datetime.date.fromisoformat(APPROVAL_DATE.match(first, m.end()).group(1))
            for m in APPROVAL_OPEN.finditer(first)]


def approval(block: str | None, since: datetime.date | None = None,
             today: datetime.date | None = None) -> str:
    """Whether a Next block pre-approves its next step, for /pass's resume mode. MALFORMED when
    any `(approved by Hayden` in the block lacks a real ISO date (the handoff skill writes the
    marker only for an approval given in the session, citing its date). Otherwise only a marker
    on the first item (first_item) counts, since an approval covers one step: APPROVED when it
    carries `(approved by Hayden YYYY-MM-DD)` dated within the session, UNAPPROVED when the
    first item has no marker. A first-item marker is STALE when it is dated before `since` (the
    session's start date, local time: the approval came from an earlier session), after `today`
    (no approval comes from the future), or when `since` is None (an unknown start can't confirm
    it). A same-day marker from an earlier session can't be told apart by its date, so it counts.
    A marker on a later item is ignored."""
    for m in APPROVAL_OPEN.finditer(block or ""):
        date = APPROVAL_DATE.match(block, m.end())
        try:
            datetime.date.fromisoformat(date.group(1) if date else "")
        except ValueError:
            return MALFORMED
    dates = approval_dates(block)
    if not dates:
        return UNAPPROVED
    today = today or datetime.date.today()
    return STALE if since is None or min(dates) < since or max(dates) > today else APPROVED


def config_dir() -> str:
    """Claude Code's config dir: $CLAUDE_CONFIG_DIR, else ~/.claude."""
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def sessions_dir() -> str:
    return os.path.join(config_dir(), "sessions")


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
    """Claude Code's per-process session files whose process exists (session_state), stopped or
    not: a stopped session still holds its lane, so `open` and seed_line leave it be. None when
    pids can't be seen."""
    if not pids_visible():
        return None
    return [s for s in session_files() if session_state(s) is not None]


def inside(path: str, root: str) -> bool:
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def cwd_inside(value, root: str) -> bool:
    """inside() for a cwd read from a file: a string with no NUL (realpath raises on one)."""
    return isinstance(value, str) and "\0" not in value and inside(value, root)


# ---- processes ------------------------------------------------------------------------------
# `lane done` decides what to end from kernel facts (/proc) and Claude Code's own files (session
# files, transcripts), which sandboxed Bash can't write; never from lane.json, which it can. Any
# read here may race the process's exit, so an OSError means "gone or unknown", never a crash.

PROC = "/proc"
EXITED = ("Z", "X")  # /proc/<pid>/stat states of a process that has exited (zombie, dead)
STOPPED = ("T", "t")  # stopped (Ctrl+Z) and traced: tmux/claude-saved's stopped() reads the same
TRANSCRIPT_HEAD = 64 * 1024  # bytes of a transcript read for its first recorded cwd


class Proc(NamedTuple):
    """One process as a /proc scan saw it. (pid, start) names it: a pid alone may be reused."""
    pid: int
    ppid: int
    start: int  # /proc/<pid>/stat field 22, clock ticks since boot
    state: str  # field 3
    comm: str
    cwd: str | None  # None when unreadable (a zombie has none)
    argv: tuple[str, ...]


def proc_stat(pid: int, proc: str = PROC) -> tuple[str, str, int, int] | None:
    """(comm, state, ppid, start) from /proc/<pid>/stat, or None. The comm sits in parentheses
    and may hold spaces and ')' itself, so the fields are split after the last ')'."""
    try:
        with open(os.path.join(proc, str(pid), "stat"), "rb") as f:
            raw = f.read().decode(errors="replace")
    except OSError:
        return None
    head, sep, rest = raw.rpartition(")")
    fields = rest.split()
    if not sep or "(" not in head or len(fields) < 20:
        return None
    try:
        return head.partition("(")[2], fields[0], int(fields[1]), int(fields[19])
    except ValueError:
        return None


def proc_start(pid: int, proc: str = PROC) -> int | None:
    st = proc_stat(pid, proc)
    return st[3] if st else None


def proc_alive(p: Proc, proc: str = PROC) -> bool:
    """Whether p still runs: its pid names the same process (same start) and it hasn't exited."""
    st = proc_stat(p.pid, proc)
    return st is not None and st[3] == p.start and st[1] not in EXITED


def proc_env_sid(pid: int, proc: str = PROC) -> str | None:
    """The CLAUDE_CODE_SESSION_ID that pid was started with, when it is a session id (SID), else
    None. Raises OSError when the environment can't be read (gone, another user's)."""
    with open(os.path.join(proc, str(pid), "environ"), "rb") as f:
        raw = f.read()
    for entry in raw.split(b"\0"):
        if entry.startswith(b"CLAUDE_CODE_SESSION_ID="):
            sid = entry.partition(b"=")[2].decode(errors="replace")
            return sid if SID.fullmatch(sid) else None
    return None


def scan(proc: str = PROC, full: bool = True) -> dict[int, Proc]:
    """Every process, from one pass over /proc: pid -> Proc. One that exits mid-scan is left out.
    full=False reads only each stat (cwd None, argv empty): the process tree, faster."""
    out = {}
    try:
        names = os.listdir(proc)
    except OSError:
        return out
    for name in names:
        if not (name.isascii() and name.isdigit()):
            continue
        pid = int(name)
        st = proc_stat(pid, proc)
        if st is None:
            continue
        if not full:
            out[pid] = Proc(pid, st[2], st[3], st[1], st[0], None, ())
            continue
        base = os.path.join(proc, name)
        try:
            cwd = os.readlink(os.path.join(base, "cwd"))
        except OSError:
            cwd = None
        try:
            with open(os.path.join(base, "cmdline"), "rb") as f:
                raw = f.read().rstrip(b"\0")
            argv = tuple(a.decode(errors="replace") for a in raw.split(b"\0")) if raw else ()
        except OSError:
            argv = ()
        out[pid] = Proc(pid, st[2], st[3], st[1], st[0], cwd, argv)
    return out


def children(procs: dict[int, Proc]) -> dict[int, list[int]]:
    """ppid -> the pids of its children that haven't exited, from one scan."""
    out = {}
    for p in procs.values():
        if p.state not in EXITED:
            out.setdefault(p.ppid, []).append(p.pid)
    return out


def ancestors(pid: int, procs: dict[int, Proc]) -> list[int]:
    """pid's parent chain in one scan, nearest first; it stops at a pid the scan lacks."""
    out, seen = [], {pid}
    while (p := procs.get(pid)) and p.ppid > 0 and p.ppid not in seen:
        out.append(p.ppid)
        seen.add(p.ppid)
        pid = p.ppid
    return out


def descendants(pid: int, kids: dict[int, list[int]]) -> list[int]:
    """Every process whose parent chain reaches pid (children())."""
    out, todo, seen = [], list(kids.get(pid, [])), {pid}
    while todo:
        child = todo.pop()
        if child not in seen:
            seen.add(child)
            out.append(child)
            todo.extend(kids.get(child, []))
    return out


def open_under(pid: int, root: str, proc: str = PROC) -> str | None:
    """A file pid holds open under root (by its /proc fd links), "(its open files can't be
    read)" when they can't be listed while it runs, or None."""
    fd_dir = os.path.join(proc, str(pid), "fd")
    try:
        fds = os.listdir(fd_dir)
    except FileNotFoundError:
        return None
    except OSError:
        return "(its open files can't be read)"
    prefix = os.path.realpath(root).rstrip(os.sep) + os.sep
    for fd in fds:
        try:
            target = os.readlink(os.path.join(fd_dir, fd))
        except OSError:
            continue
        if target.startswith(prefix):
            return target
    return None


def read_head(path: str, limit: int) -> bytes | None:
    """Up to limit bytes of a regular file, or None: gone, unreadable, or no regular file (a
    FIFO's open would wait for a writer)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        chunks, left = [], limit
        while left > 0 and (chunk := os.read(fd, left)):
            chunks.append(chunk)
            left -= len(chunk)
        return b"".join(chunks)
    except OSError:
        return None
    finally:
        os.close(fd)


def session_files() -> list[dict]:
    """Claude Code's per-process session files (<config>/sessions/<pid>.json), live or stale,
    each a JSON object. They outlive their process, so a pid in one proves nothing alone."""
    out = []
    for path in glob.glob(os.path.join(sessions_dir(), "*.json")):
        try:
            s = json.loads(read_head(path, 1 << 20) or b"null")
        except ValueError:
            continue
        if isinstance(s, dict):
            out.append(s)
    return out


def proc_start_of(session: dict) -> int | None:
    """A session file's procStart (an int, or the digit string Claude Code writes), or None."""
    v = session.get("procStart")
    if isinstance(v, str) and re.fullmatch(r"[0-9]{1,20}", v):
        return int(v)
    return v if type(v) is int else None


def session_state(session: dict, proc: str = PROC) -> str | None:
    """The /proc/<pid>/stat state of a session file's process while it exists: its pid names the
    same process (procStart is stat field 22, so a reused pid fails) and it hasn't exited; else
    None. A file without a procStart can't be told from a reused pid, so it counts as gone."""
    pid, start = session.get("pid"), proc_start_of(session)
    if type(pid) is not int or pid <= 0 or start is None:
        return None
    st = proc_stat(pid, proc)
    return st[1] if st is not None and st[3] == start and st[1] not in EXITED else None


def session_running(session: dict, proc: str = PROC) -> bool:
    """Whether a session file's process exists (session_state) and isn't stopped. A stopped
    claude (Ctrl+Z) answers nothing until it is continued, but its socket still accepts
    connections, so a send to it waits out its timeout."""
    state = session_state(session, proc)
    return state is not None and state not in STOPPED


def session_stopped(session: dict, proc: str = PROC) -> bool:
    """Whether a session file's process exists (session_state) and is stopped: present, so no
    second session starts beside it, yet deaf until `fg` continues it."""
    return session_state(session, proc) in STOPPED


def socket_of(session: dict) -> str | None:
    """A session file's messagingSocketPath when it names a socket this user owns: absolute,
    printable (it is printed as an address, so no control characters or line breaks), and still
    on disk. A stale file's socket is usually gone, but a crash can leave one behind:
    session_running decides liveness."""
    path = session.get("messagingSocketPath")
    if not isinstance(path, str) or not os.path.isabs(path) or not path.isprintable():
        return None
    try:
        st = os.lstat(path)
    except OSError:
        return None
    return path if stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid() else None


def transcript_cwd(path: str) -> str | None:
    """The first cwd a transcript records, from its first TRANSCRIPT_HEAD bytes, or None."""
    for line in (read_head(path, TRANSCRIPT_HEAD) or b"").splitlines():
        try:
            rec = json.loads(line)
        except ValueError:  # the line cut at the limit, or not JSON
            continue
        if isinstance(rec, dict) and isinstance(rec.get("cwd"), str):
            return rec["cwd"]
    return None


def lane_sid(sid, path: str, files: list[dict]) -> bool:
    """Whether Claude Code's own records place session sid in the lane at path: a session file
    (session_files(), live or stale) with that sessionId and a cwd inside it, or a transcript
    <config>/projects/*/<sid>.jsonl whose first recorded cwd is inside it. lane.json's
    sessions[] is never proof: sandboxed Bash can write it."""
    if not isinstance(sid, str) or not SID.fullmatch(sid):
        return False
    if any(s.get("sessionId") == sid and cwd_inside(s.get("cwd"), path) for s in files):
        return True
    return any(cwd_inside(transcript_cwd(t), path)
               for t in glob.glob(os.path.join(config_dir(), "projects", "*", sid + ".jsonl")))


# ---- the lead -------------------------------------------------------------------------------
# The lead is the main-checkout session that last acted as lead (a bare `lane init`, `new`,
# `adopt`, `open` or `done`, or `lane lead`), recorded at Repo.lead_path. `lane addr lead`, the
# board's main-checkout footer and tmux/tmux-tab-bar only read the record, so a look never takes
# the lead. Its tmux facts come from the claude process's own environment, never its session
# file's `tmux` field: that names a tmux session, not a server, and pane ids restart at %0 on
# every server.

ENVIRON_MAX = 1 << 20  # bytes of /proc/<pid>/environ read for TMUX and TMUX_PANE
LEAD_MAX = 4096  # bytes of a lead record; a longer one is no record
PANE = re.compile(r"%[0-9]{1,9}")
NUMBER = re.compile(r"[0-9]{1,20}")


def proc_tmux(pid: int, proc: str = PROC) -> tuple[str, int, int, str] | None:
    """(socket, serverPid, serverStart, pane) from the TMUX and TMUX_PANE pid was started with,
    or None outside tmux or when a part is missing or malformed. TMUX is `socket,pid,session`,
    split from the right as tmux-tab-bar's server_key splits it (a socket path may hold a comma).
    serverStart is the server pid's stat field 22, so a server pid reused after a tmux restart
    fails a match. Read bounded, never through a link or waiting on a FIFO (read_head)."""
    raw = read_head(os.path.join(proc, str(pid), "environ"), ENVIRON_MAX)
    env = {}
    for entry in (raw or b"").split(b"\0"):
        key, sep, value = entry.partition(b"=")
        if sep and key in (b"TMUX", b"TMUX_PANE"):
            try:
                env[key] = value.decode()
            except UnicodeDecodeError:
                return None
    parts = env.get(b"TMUX", "").rsplit(",", 2)
    pane = env.get(b"TMUX_PANE", "")
    if len(parts) != 3 or not PANE.fullmatch(pane) or not NUMBER.fullmatch(parts[1]):
        return None
    socket, server = parts[0], int(parts[1])
    if not (os.path.isabs(socket) and socket.isprintable()) or server <= 0:
        return None
    start = proc_start(server, proc)
    return None if start is None else (socket, server, start, pane)


def lead_record(session: dict, tmux: tuple[str, int, int, str] | None) -> dict:
    """The record naming a session (a session file whose process runs) with its proc_tmux."""
    return {"pid": session["pid"], "procStart": proc_start_of(session),
            "sessionId": session.get("sessionId"), "tmux": list(tmux) if tmux else None,
            "at": now_iso()}


def write_lead(repo: Repo, record: dict) -> None:
    """Atomic. The state dir is out of the sandbox's reach, so only a bare command gets here."""
    write_json(repo.lead_path, record)


def read_lead(repo: Repo) -> dict | None:
    """The lead record with its shape checked ({pid, procStart, sessionId, tmux, at}, tmux a
    tuple or None), or None when it is missing, too long, not JSON, nested deeper than json
    parses (RecursionError: before 3.12, or in pure Python, near the recursion limit of 1000
    levels, which LEAD_MAX bytes reach) or of another shape. Only bare commands write it, but
    it is read as data all the same: a bad one names no lead."""
    data = read_head(repo.lead_path, LEAD_MAX + 1)
    if data is None or len(data) > LEAD_MAX:
        return None
    try:
        rec = json.loads(data)
    except (ValueError, RecursionError):  # json recurses on nesting, as tmux-tab-bar knows
        return None
    if not isinstance(rec, dict):
        return None
    pid, start, sid, tmux, at = (rec.get(k) for k in ("pid", "procStart", "sessionId", "tmux",
                                                      "at"))
    if type(pid) is not int or pid <= 0 or type(start) is not int or start < 0:
        return None
    if not (isinstance(sid, str) and SID.fullmatch(sid)) or not isinstance(at, str):
        return None
    if tmux is not None:
        if not (isinstance(tmux, list) and len(tmux) == 4):
            return None
        socket, server, server_start, pane = tmux
        if not (isinstance(socket, str) and os.path.isabs(socket) and socket.isprintable()
                and type(server) is int and server > 0 and type(server_start) is int
                and server_start >= 0 and isinstance(pane, str) and PANE.fullmatch(pane)):
            return None
        tmux = (socket, server, server_start, pane)
    return {"pid": pid, "procStart": start, "sessionId": sid, "tmux": tmux, "at": at}


def main_sessions(repo: Repo) -> list[dict]:
    """The live sessions in the main checkout, by pid: session files whose process runs
    (session_running: a stopped one answers nothing), with a socket (socket_of: a `claude -p` has none, so it never counts)
    and a cwd inside repo.main, agent worktrees under it included. `lane addr lead`, the board's
    footer and lead_of share this one set. Call it only where pids_visible()."""
    return sorted((s for s in session_files() if cwd_inside(s.get("cwd"), repo.main)
                   and session_running(s) and socket_of(s)), key=lambda s: s["pid"])


def lead_of(repo: Repo, sessions: list[dict]) -> dict | None:
    """The lead among main_sessions(repo), which run (a stopped one is out of reach): the one
    whose pid and procStart the record holds (a /clear keeps both); else the record's one
    continuation, a session with the record's session id (a resume: in the same tab, another,
    or a tmux restart's restored tab) or one whose own environment names the record's tmux
    server (socket, pid and start) and pane (a /pass successor: `respawn-pane -k` keeps the
    pane). Two continuations (a resume beside a fresh claude in the old pane, two resumes, a
    child claude that inherits TMUX_PANE) give None. With none, one session is the lead, as
    long as the recorded process isn't stopped (Ctrl+Z): beside a lead that `fg` brings back,
    the one running is likely a side chat (Hayden's call, 2026-10-17). Else None."""
    if not sessions:
        return None
    rec = read_lead(repo)
    if rec is not None:
        for s in sessions:
            if s["pid"] == rec["pid"] and proc_start_of(s) == rec["procStart"]:
                return s
        on = {s["pid"]: s for s in sessions if s.get("sessionId") == rec["sessionId"]
              or (rec["tmux"] is not None and proc_tmux(s["pid"]) == rec["tmux"])}
        if len(on) == 1:
            return next(iter(on.values()))
    if len(sessions) == 1 and not (rec is not None and session_stopped(rec)):
        return sessions[0]
    return None


def stopped_lead(repo: Repo) -> dict | None:
    """The recorded lead when its process exists and is stopped (Ctrl+Z): its session file (by
    pid and procStart), or {"pid"} when none names it; else None. The refusals and the board
    footer name it, so Hayden knows which tab to `fg` in."""
    rec = read_lead(repo)
    if rec is None or not session_stopped(rec):
        return None
    for s in session_files():
        if type(s.get("pid")) is int and s["pid"] == rec["pid"] \
                and proc_start_of(s) == rec["procStart"]:
            return s
    return {"pid": rec["pid"]}
