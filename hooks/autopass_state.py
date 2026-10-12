"""autopass state: the context tiers, the per-tab /autopass flag and whether auto-pass is on.

Shared by hooks/context_watch.py (the watcher), hooks/autopass_toggle.py (/autopass) and, later,
the statusline widget and `lane ls`. Each puts this file's real directory on sys.path itself
(python3 -I keeps it off). Stdlib only; keep the source ASCII. PLAN.md "PR 4: auto-pass" has
the design.

- window(): `autoCompactWindow` from ~/.claude/settings.json (statusline/ctx-breakdown.py's
  autocompact_setting reads it the same way; that file is copied into ccstatusline's own config
  dir, so it can't import this one), else 600000.
- tiers(window): soft = window // 2, wrap = window - 120000, hard = window - 80000 and
  compact_at = window - 33000, where Claude Code really compacts (spike-measured, about 567k).
  `tiers = [soft, wrap, hard]` in ~/.config/dotclaude/pass.toml overrides the three for live
  tests; a value that isn't three increasing positive integers below compact_at is ignored.
  A window too small for the derived tiers to increase gives None (the watcher stays quiet).
- The tab flag, $XDG_STATE_HOME/dotclaude/autopass/<pane number>.json = {tab, on, set_at}, holds
  what /autopass on|off set in that tmux tab. It counts only while its tab (socket, server
  start, server pid, pane: pass-respawn's pane_tab key) matches this pane on this server
  exactly, so a flag a dead server left behind is ignored.
- decide(cwd, pane) -> (on, source): the tab flag ("tab"), else the repo's lanes config key
  `autopass` when cwd is a lane, true by default there ("lanes"), else `autopass` in pass.toml
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
SOFT_SHARE, WRAP_MARGIN, HARD_MARGIN, COMPACT_BUFFER = 2, 120000, 80000, 33000
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


def window() -> int:
    return autocompact_setting(os.path.expanduser("~/.claude")) or DEFAULT_WINDOW


def pass_toml() -> dict:
    """~/.config/dotclaude/pass.toml, or {} when it is missing or not TOML."""
    try:
        with open(pass_toml_path(), "rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}


def tiers(win: int | None = None, config: dict | None = None) -> dict | None:
    """{"soft", "wrap", "hard", "compact_at"} in tokens, or None when neither the derived tiers
    nor an override increase (a window under 280k)."""
    win = window() if win is None else win
    compact_at = win - COMPACT_BUFFER
    override = (pass_toml() if config is None else config).get("tiers")
    if (isinstance(override, list) and len(override) == 3 and all(map(is_int, override))
            and 0 < override[0] < override[1] < override[2] < compact_at):
        soft, wrap, hard = override
    else:
        soft, wrap, hard = win // SOFT_SHARE, win - WRAP_MARGIN, win - HARD_MARGIN
        if not 0 < soft < wrap < hard < compact_at:
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


def set_flag(pane: str, the_tab: dict, on: bool) -> None:
    write_json(flag_path(pane), {"tab": the_tab, "on": on, "set_at": time.time()})


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
    """The lanes config's `autopass` (true by default) when cwd is a registered lane, else
    None. Any failure (no git, no lanes, a broken config) is None."""
    lib = lanelib() if isinstance(cwd, str) and os.path.isdir(cwd) else None
    if lib is None:
        return None
    try:
        repo = lib.resolve(cwd)
        if repo is None or repo.identity()[0] != "lane":
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
    """{tokens, time}: the session's context size at its latest Stop or tool call."""
    return os.path.join(state_dir(), "ctx", sid + ".json")


def watch_path(sid: str) -> str:
    """The watcher's own record of the session: which tiers fired, and a cached decide()."""
    return os.path.join(state_dir(), "ctx-watch", sid + ".json")


@contextlib.contextmanager
def watch_lock(wait: float = 1.0):
    """An exclusive flock on ctx-watch/.lock, so two hooks of one session (parallel tool calls)
    never fire a tier twice. Yields False when it wasn't taken within `wait` seconds."""
    d = os.path.join(state_dir(), "ctx-watch")
    os.makedirs(d, exist_ok=True)
    fd = os.open(os.path.join(d, ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    yield False
                    return
                time.sleep(0.02)
        yield True
    finally:
        os.close(fd)
