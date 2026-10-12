"""autopass state: the context tiers, the per-tab /autopass flag and whether auto-pass is on.

Shared by hooks/context_watch.py (the watcher), hooks/autopass_toggle.py (/autopass),
statusline/ctx-breakdown.py (the ctx widget) and `lane ls`. Each puts this file's real directory
on sys.path itself (python3 -I keeps it off; setup.sh symlinks the widget into ccstatusline's
config dir, so its real path finds hooks/). Stdlib only; keep the source ASCII. PLAN.md "PR 4:
auto-pass" has the design.

- window(transcript_path, model_window): `autoCompactWindow` from the config dir's
  settings.json, the dir found from the transcript path, else 600000. When the model's own
  window is known (the ctx file's `window`, which the statusline widget writes from
  context_window.context_window_size; no hook payload names the model) and sane, the smaller
  of the two.
- tiers(window): compact_at = window - 33000, where Claude Code really compacts
  (spike-measured, about 567k); hard = compact_at - min(47000, 8% of the window) (47k is the
  p90 handoff cost); wrap = hard - min(40000, 7% of the window) (40k is about one turn); soft =
  window // 2. The margins scale down so a small window isn't eaten by them, and are capped at
  the 600k values: 600k gives 300k/480k/520k/567k, 200k gives 100k/137k/151k/167k, 150k gives
  75k/94.5k/105k/117k. When soft would reach wrap-up, or wrap-up would sit under 60k (a
  session starts near 40k, so the first Stop would nudge), tiers is None and the watcher stays
  quiet: any window under about 110k. `tiers = [soft, wrap, hard]` in
  ~/.config/dotclaude/pass.toml overrides the three for live tests; a value that isn't three
  increasing positive integers below compact_at is ignored.
- The ctx file, ctx/<session>.json = {tokens, time, window?, window_at?}: the watcher writes
  tokens and time, the widget window and window_at. Both merge through merge_ctx(), under the
  session's ctx lock (ctx-watch/<session>.ctx.lock, apart from the watcher's own), so neither
  rolls back the other's fields.
- The tab flag, $XDG_STATE_HOME/dotclaude/autopass/<pane number>.json = {tab, on, set_at}, holds
  what /autopass on|off set in that tmux tab. It counts only while its tab (socket, server
  start, server pid, pane: pass-respawn's pane_tab key) matches this pane on this server
  exactly, so a flag a dead server left behind is ignored.
- decide(cwd, pane) -> (on, source): the tab flag ("tab"), else the repo's lanes config key
  `autopass` when cwd is a lane or the main checkout of a lanes repo (the lead passes itself
  the same way), true by default there ("lanes"), else `autopass` in pass.toml
  ("pass.toml"), else off ("default"). It runs git and maybe tmux, so call it only when a tier
  would fire.
"""
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import tomllib

DEFAULT_WINDOW = 600000
COMPACT_BUFFER, HANDOFF_COST, TURN = 33000, 47000, 40000  # the margins' caps
HARD_SHARE, WRAP_SHARE = 8, 7  # percent of the window, under the caps
MIN_WRAP = 60000               # a session starts near 40k: a wrap-up under this nudges at once
WINDOW_RANGE = (50000, 10_000_000)  # a model window outside this is garbage
TIER_NAMES = ("soft", "wrap", "hard")
PANE = re.compile(r"%\d+")
HERE = os.path.dirname(os.path.realpath(__file__))
LANES_SCRIPTS = os.path.join(HERE, "..", "skills", "lanes", "scripts")


def state_dir() -> str:
    return os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"),
                        "dotclaude")


def pass_toml_path() -> str:
    return os.path.expanduser("~/.config/dotclaude/pass.toml")


def is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def autocompact_setting(cfg: str):
    """autoCompactWindow from the config dir's settings.json, if set to a positive number."""
    try:
        with open(os.path.join(cfg, "settings.json"), encoding="utf-8") as f:
            v = json.load(f).get("autoCompactWindow")
    except (OSError, ValueError, AttributeError):
        return None
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else None


def config_dir(transcript_path) -> str:
    """The active config dir: <config-dir>/projects/<project>/<session>.jsonl, else
    CLAUDE_CONFIG_DIR, else ~/.claude (ctx-breakdown.py's config_dir)."""
    if isinstance(transcript_path, str) and transcript_path:
        if os.path.basename(os.path.dirname(os.path.dirname(transcript_path))) == "projects":
            return os.path.dirname(os.path.dirname(os.path.dirname(transcript_path)))
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")


def window(transcript_path=None, model_window=None) -> int:
    win = autocompact_setting(config_dir(transcript_path)) or DEFAULT_WINDOW
    if is_int(model_window) and WINDOW_RANGE[0] <= model_window <= WINDOW_RANGE[1]:
        win = min(win, model_window)
    return win


def pass_toml() -> dict:
    """~/.config/dotclaude/pass.toml, or {} when it is missing or not TOML."""
    try:
        with open(pass_toml_path(), "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}


def tiers(win: int | None = None, config: dict | None = None) -> dict | None:
    """{"soft", "wrap", "hard", "compact_at"} in tokens, or None when neither the derived tiers
    nor an override can increase."""
    win = window() if win is None else win
    compact_at = win - COMPACT_BUFFER
    override = (pass_toml() if config is None else config).get("tiers")
    if (isinstance(override, list) and len(override) == 3 and all(map(is_int, override))
            and 0 < override[0] < override[1] < override[2] < compact_at):
        soft, wrap, hard = override
    else:
        hard = compact_at - min(HANDOFF_COST, win * HARD_SHARE // 100)
        wrap = hard - min(TURN, win * WRAP_SHARE // 100)
        soft = win // 2
        if soft >= wrap or wrap < MIN_WRAP or not 0 < soft < wrap < hard < compact_at:
            return None
    return {"soft": soft, "wrap": wrap, "hard": hard, "compact_at": compact_at}


def kilo(tokens: int) -> str:
    return "%dk" % round(tokens / 1000)


def tab(pane: str) -> dict | None:
    """This pane on its tmux server, keyed as pass-respawn's pane_tab keys it, or None."""
    if not isinstance(pane, str) or not PANE.fullmatch(pane):
        return None
    try:
        p = subprocess.run(["tmux", "display", "-p", "-t", pane,
                            "#{start_time} #{pid} #{socket_path}"],
                           capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return None
    parts = p.stdout.rstrip("\n").split(" ", 2) if p.returncode == 0 else []
    if len(parts) != 3 or not (parts[0].isdigit() and parts[1].isdigit()) or not parts[2]:
        return None
    return {"socket": parts[2], "server_start": int(parts[0]), "server_pid": int(parts[1]),
            "pane": pane}


def flag_path(pane: str) -> str:
    return os.path.join(state_dir(), "autopass", pane[1:] + ".json")


def load_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(path: str, data) -> None:
    """Atomic: a temp file beside path, renamed over it."""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def flag_generation(pane) -> str:
    """A token that changes with every write of the pane's flag: its `generation` counter, or
    "absent" (no pane, no flag, or one without a counter). The watcher's cached decide() is
    valid only while this is what it was when decide() ran, so a toggle between a hook's
    decide() and its store can't leave a stale answer cached."""
    if not isinstance(pane, str) or not PANE.fullmatch(pane):
        return "absent"
    flag = load_json(flag_path(pane))
    gen = flag.get("generation") if isinstance(flag, dict) else None
    return "g%d" % gen if is_int(gen) else "absent"


def set_flag(pane: str, the_tab: dict, on: bool) -> None:
    """Write the tab flag with the next generation, so two writes in one mtime tick differ."""
    old = load_json(flag_path(pane))
    gen = old.get("generation") if isinstance(old, dict) else None
    write_json(flag_path(pane), {"tab": the_tab, "on": on, "set_at": time.time(),
                                 "generation": (gen if is_int(gen) else 0) + 1})


def tab_flag(pane: str):
    """The tab flag's `on` when it was set in this very tab, else None. tmux is asked only when
    a flag file exists."""
    if not isinstance(pane, str) or not PANE.fullmatch(pane):
        return None
    flag = load_json(flag_path(pane))
    if not isinstance(flag, dict) or not isinstance(flag.get("on"), bool):
        return None
    here = tab(pane)
    return flag["on"] if here is not None and flag.get("tab") == here else None


def lanelib():
    """skills/lanes/scripts/lanelib, found from this file's real path, or None."""
    if LANES_SCRIPTS not in sys.path:
        sys.path.insert(0, LANES_SCRIPTS)
    try:
        import lanelib as mod
    except Exception:
        return None
    return mod


def lane_setting(cwd: str):
    """The lanes config's `autopass` (true by default) when cwd is a registered lane or the
    main checkout of a lanes repo, else None. Any failure (no git, no lanes, a broken config) is None."""
    lib = lanelib() if isinstance(cwd, str) and os.path.isdir(cwd) else None
    if lib is None:
        return None
    try:
        repo = lib.resolve(cwd)
        if repo is None or repo.identity()[0] not in ("lane", "main"):
            return None
        v = repo.config().get("autopass", True)
    except Exception:
        return None
    return v if isinstance(v, bool) else True


def decide(cwd: str, pane: str | None) -> tuple[bool, str]:
    """(on, source): the tab flag, then the lanes config in a lane, then pass.toml, then off."""
    flag = tab_flag(pane) if pane else None
    if flag is not None:
        return flag, "tab"
    lane = lane_setting(cwd)
    if lane is not None:
        return lane, "lanes"
    v = pass_toml().get("autopass")
    if isinstance(v, bool):
        return v, "pass.toml"
    return False, "default"


# ---- the watcher's files, shared with /autopass ----

def ctx_path(sid: str) -> str:
    """{tokens, time}: the session's context size at its latest Stop or tool call, plus the
    widget's {window, window_at}."""
    return os.path.join(state_dir(), "ctx", sid + ".json")


def read_ctx(sid: str) -> dict:
    rec = load_json(ctx_path(sid))
    return rec if isinstance(rec, dict) else {}


def merge_ctx(sid: str, fields: dict, wait: float = 1.0) -> dict | None:
    """Merge fields into the ctx file, keeping its others, under the session's ctx lock
    (ctx-watch/<session>.ctx.lock), so the watcher and the widget never roll back each other's
    fields. The new record, or None when the lock stayed busy for `wait` seconds and nothing
    was written."""
    with watch_lock(sid, wait, kind=".ctx") as locked:
        if not locked:
            return None
        old = read_ctx(sid)
        stamp = old.get("time")
        if ("time" in fields and isinstance(stamp, (int, float)) and not isinstance(stamp, bool)
                and stamp > fields["time"]):
            # An older count landing after a newer one (two parallel tool calls): keep the newer.
            fields = {k: v for k, v in fields.items() if k not in ("tokens", "time")}
        rec = {**old, **fields}
        write_json(ctx_path(sid), rec)
    return rec


def write_ctx(sid: str, tokens: int, now: float) -> dict:
    """Merge {tokens, time} into the ctx file (merge_ctx). With the lock busy past a second the
    write is skipped (the next event writes) and the merged record is still returned."""
    fields = {"tokens": tokens, "time": now}
    rec = merge_ctx(sid, fields)
    return rec if rec is not None else {**read_ctx(sid), **fields}


def watch_path(sid: str) -> str:
    """The watcher's own record of the session: which tiers fired, and a cached decide()."""
    return os.path.join(state_dir(), "ctx-watch", sid + ".json")


@contextlib.contextmanager
def watch_lock(sid: str, wait: float = 1.0, kind: str = ""):
    """An exclusive flock on ctx-watch/<session>.lock, so two hooks of one session (parallel
    tool calls) never fire a tier twice. Nothing slow runs under it (decide() runs before).
    kind ".ctx" is merge_ctx's own lock, <session>.ctx.lock, apart from the watcher's, so a busy
    watcher never holds up the count. Yields False when it wasn't taken within `wait` seconds."""
    d = os.path.join(state_dir(), "ctx-watch")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, sid + kind + ".lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.02)
                continue
            try:
                same = os.fstat(fd).st_ino == os.stat(path).st_ino
            except OSError:
                same = False
            if same:
                break
            # The prune unlinked the file between open and flock: a lock on the old inode
            # excludes nobody, so take the file now at the path.
            os.close(fd)
            fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.utime(fd)  # flock leaves the mtime alone; this keeps the prune off a lock in use
        except OSError:
            pass
        yield True
    finally:
        os.close(fd)
